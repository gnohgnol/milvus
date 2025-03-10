// Licensed to the LF AI & Data foundation under one
// or more contributor license agreements. See the NOTICE file
// distributed with this work for additional information
// regarding copyright ownership. The ASF licenses this file
// to you under the Apache License, Version 2.0 (the
// "License"); you may not use this file except in compliance
// with the License. You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

package grpcclient

import (
	"context"
	"crypto/tls"
	"fmt"
	"sync"
	"time"

	"go.uber.org/zap"
	"google.golang.org/grpc"
	"google.golang.org/grpc/backoff"
	"google.golang.org/grpc/credentials"
	"google.golang.org/grpc/keepalive"

	grpcopentracing "github.com/grpc-ecosystem/go-grpc-middleware/tracing/opentracing"
	"github.com/milvus-io/milvus/internal/log"
	"github.com/milvus-io/milvus/internal/util"
	"github.com/milvus-io/milvus/internal/util/crypto"
	"github.com/milvus-io/milvus/internal/util/funcutil"
	"github.com/milvus-io/milvus/internal/util/generic"
	"github.com/milvus-io/milvus/internal/util/trace"
)

// GrpcClient abstracts client of grpc
type GrpcClient[T any] interface {
	SetRole(string)
	GetRole() string
	SetGetAddrFunc(func() (string, error))
	EnableEncryption()
	SetNewGrpcClientFunc(func(cc *grpc.ClientConn) T)
	GetGrpcClient(ctx context.Context) (T, error)
	ReCall(ctx context.Context, caller func(client T) (any, error)) (any, error)
	Call(ctx context.Context, caller func(client T) (any, error)) (any, error)
	Close() error
	SetNodeID(int64)
	GetNodeID() int64
}

// ClientBase is a base of grpc client
type ClientBase[T any] struct {
	getAddrFunc   func() (string, error)
	newGrpcClient func(cc *grpc.ClientConn) T

	grpcClient             T
	encryption             bool
	conn                   *grpc.ClientConn
	grpcClientMtx          sync.RWMutex
	role                   string
	ClientMaxSendSize      int
	ClientMaxRecvSize      int
	RetryServiceNameConfig string

	DialTimeout      time.Duration
	KeepAliveTime    time.Duration
	KeepAliveTimeout time.Duration

	MaxAttempts       int
	InitialBackoff    float32
	MaxBackoff        float32
	BackoffMultiplier float32
	NodeID            int64
}

// SetRole sets role of client
func (c *ClientBase[T]) SetRole(role string) {
	c.role = role
}

// GetRole returns role of client
func (c *ClientBase[T]) GetRole() string {
	return c.role
}

// SetGetAddrFunc sets getAddrFunc of client
func (c *ClientBase[T]) SetGetAddrFunc(f func() (string, error)) {
	c.getAddrFunc = f
}

func (c *ClientBase[T]) EnableEncryption() {
	c.encryption = true
}

// SetNewGrpcClientFunc sets newGrpcClient of client
func (c *ClientBase[T]) SetNewGrpcClientFunc(f func(cc *grpc.ClientConn) T) {
	c.newGrpcClient = f
}

// GetGrpcClient returns grpc client
func (c *ClientBase[T]) GetGrpcClient(ctx context.Context) (T, error) {
	c.grpcClientMtx.RLock()

	if !generic.IsZero(c.grpcClient) {
		defer c.grpcClientMtx.RUnlock()
		return c.grpcClient, nil
	}
	c.grpcClientMtx.RUnlock()

	c.grpcClientMtx.Lock()
	defer c.grpcClientMtx.Unlock()

	if !generic.IsZero(c.grpcClient) {
		return c.grpcClient, nil
	}

	err := c.connect(ctx)
	if err != nil {
		return generic.Zero[T](), err
	}

	return c.grpcClient, nil
}

func (c *ClientBase[T]) resetConnection(client T) {
	c.grpcClientMtx.Lock()
	defer c.grpcClientMtx.Unlock()
	if generic.IsZero(c.grpcClient) {
		return
	}
	if !generic.Equal(client, c.grpcClient) {
		return
	}
	if c.conn != nil {
		_ = c.conn.Close()
	}
	c.conn = nil
	c.grpcClient = generic.Zero[T]()
}

func (c *ClientBase[T]) connect(ctx context.Context) error {
	addr, err := c.getAddrFunc()
	if err != nil {
		log.Error("failed to get client address", zap.Error(err))
		return err
	}

	opts := trace.GetInterceptorOpts()
	dialContext, cancel := context.WithTimeout(ctx, c.DialTimeout)

	// refer to https://github.com/grpc/grpc-proto/blob/master/grpc/service_config/service_config.proto
	retryPolicy := fmt.Sprintf(`{
		"methodConfig": [{
		  "name": [{"service": "%s"}],
		  "retryPolicy": {
			  "MaxAttempts": %d,
			  "InitialBackoff": "%fs",
			  "MaxBackoff": "%fs",
			  "BackoffMultiplier": %f,
			  "RetryableStatusCodes": [ "UNAVAILABLE" ]
		  }
		}]}`, c.RetryServiceNameConfig, c.MaxAttempts, c.InitialBackoff, c.MaxBackoff, c.BackoffMultiplier)

	var conn *grpc.ClientConn
	if c.encryption {
		conn, err = grpc.DialContext(
			dialContext,
			addr,
			//grpc.WithInsecure(),
			// #nosec G402
			grpc.WithTransportCredentials(credentials.NewTLS(&tls.Config{})),
			grpc.WithBlock(),
			grpc.WithDefaultCallOptions(
				grpc.MaxCallRecvMsgSize(c.ClientMaxRecvSize),
				grpc.MaxCallSendMsgSize(c.ClientMaxSendSize),
			),
			grpc.WithUnaryInterceptor(grpcopentracing.UnaryClientInterceptor(opts...)),
			grpc.WithStreamInterceptor(grpcopentracing.StreamClientInterceptor(opts...)),
			grpc.WithDefaultServiceConfig(retryPolicy),
			grpc.WithKeepaliveParams(keepalive.ClientParameters{
				Time:                c.KeepAliveTime,
				Timeout:             c.KeepAliveTimeout,
				PermitWithoutStream: true,
			}),
			grpc.WithConnectParams(grpc.ConnectParams{
				Backoff: backoff.Config{
					BaseDelay:  100 * time.Millisecond,
					Multiplier: 1.6,
					Jitter:     0.2,
					MaxDelay:   3 * time.Second,
				},
				MinConnectTimeout: c.DialTimeout,
			}),
			grpc.WithPerRPCCredentials(&Token{Value: crypto.Base64Encode(util.MemberCredID)}),
		)
	} else {
		conn, err = grpc.DialContext(
			dialContext,
			addr,
			grpc.WithInsecure(),
			//grpc.WithTransportCredentials(credentials.NewTLS(&tls.Config{})),
			grpc.WithBlock(),
			grpc.WithDefaultCallOptions(
				grpc.MaxCallRecvMsgSize(c.ClientMaxRecvSize),
				grpc.MaxCallSendMsgSize(c.ClientMaxSendSize),
			),
			grpc.WithUnaryInterceptor(grpcopentracing.UnaryClientInterceptor(opts...)),
			grpc.WithStreamInterceptor(grpcopentracing.StreamClientInterceptor(opts...)),
			grpc.WithDefaultServiceConfig(retryPolicy),
			grpc.WithKeepaliveParams(keepalive.ClientParameters{
				Time:                c.KeepAliveTime,
				Timeout:             c.KeepAliveTimeout,
				PermitWithoutStream: true,
			}),
			grpc.WithConnectParams(grpc.ConnectParams{
				Backoff: backoff.Config{
					BaseDelay:  100 * time.Millisecond,
					Multiplier: 1.6,
					Jitter:     0.2,
					MaxDelay:   3 * time.Second,
				},
				MinConnectTimeout: c.DialTimeout,
			}),
			grpc.WithPerRPCCredentials(&Token{Value: crypto.Base64Encode(util.MemberCredID)}),
		)
	}

	cancel()
	if err != nil {
		return wrapErrConnect(addr, err)
	}
	if c.conn != nil {
		_ = c.conn.Close()
	}

	c.conn = conn
	c.grpcClient = c.newGrpcClient(c.conn)
	return nil
}

func (c *ClientBase[T]) callOnce(ctx context.Context, caller func(client T) (any, error)) (any, error) {
	client, err := c.GetGrpcClient(ctx)
	if err != nil {
		return generic.Zero[T](), err
	}

	ret, err2 := caller(client)
	if err2 == nil {
		return ret, nil
	}

	if !funcutil.CheckCtxValid(ctx) {
		return generic.Zero[T](), err2
	}
	if !funcutil.IsGrpcErr(err2) {
		log.Debug("ClientBase:isNotGrpcErr", zap.Error(err2))
		return generic.Zero[T](), err2
	}
	log.Debug(c.GetRole()+" ClientBase grpc error, start to reset connection", zap.Error(err2))
	c.resetConnection(client)
	return ret, err2
}

// Call does a grpc call
func (c *ClientBase[T]) Call(ctx context.Context, caller func(client T) (any, error)) (any, error) {
	if !funcutil.CheckCtxValid(ctx) {
		return generic.Zero[T](), ctx.Err()
	}

	ret, err := c.callOnce(ctx, caller)
	if err != nil {
		traceErr := fmt.Errorf("err: %w\n, %s", err, trace.StackTrace())
		log.Error("ClientBase Call grpc first call get error", zap.String("role", c.GetRole()), zap.Error(traceErr))
		return generic.Zero[T](), traceErr
	}
	return ret, err
}

// ReCall does the grpc call twice
func (c *ClientBase[T]) ReCall(ctx context.Context, caller func(client T) (any, error)) (any, error) {
	if !funcutil.CheckCtxValid(ctx) {
		return generic.Zero[T](), ctx.Err()
	}

	ret, err := c.callOnce(ctx, caller)
	if err == nil {
		return ret, nil
	}

	traceErr := fmt.Errorf("err: %w\n, %s", err, trace.StackTrace())
	log.Warn(c.GetRole()+" ClientBase ReCall grpc first call get error ", zap.Error(traceErr))

	if !funcutil.CheckCtxValid(ctx) {
		return generic.Zero[T](), ctx.Err()
	}

	ret, err = c.callOnce(ctx, caller)
	if err != nil {
		traceErr = fmt.Errorf("err: %w\n, %s", err, trace.StackTrace())
		log.Error("ClientBase ReCall grpc second call get error", zap.String("role", c.GetRole()), zap.Error(traceErr))
		return generic.Zero[T](), traceErr
	}
	return ret, err
}

// Close close the client connection
func (c *ClientBase[T]) Close() error {
	c.grpcClientMtx.Lock()
	defer c.grpcClientMtx.Unlock()
	if c.conn != nil {
		return c.conn.Close()
	}
	return nil
}

// SetNodeID set ID role of client
func (c *ClientBase[T]) SetNodeID(nodeID int64) {
	c.NodeID = nodeID
}

// GetNodeID returns ID of client
func (c *ClientBase[T]) GetNodeID() int64 {
	return c.NodeID
}
