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

package grpcquerycoordclient

import (
	"context"
	"errors"
	"testing"

	"github.com/milvus-io/milvus/internal/proto/querypb"
	"github.com/milvus-io/milvus/internal/util/mock"
	"google.golang.org/grpc"

	"github.com/milvus-io/milvus/internal/proxy"
	"github.com/milvus-io/milvus/internal/util/etcd"
	"github.com/stretchr/testify/assert"
)

func Test_NewClient(t *testing.T) {
	proxy.Params.InitOnce()

	ctx := context.Background()

	etcdCli, err := etcd.GetEtcdClient(&proxy.Params.EtcdCfg)
	assert.NoError(t, err)
	client, err := NewClient(ctx, proxy.Params.EtcdCfg.MetaRootPath.GetValue(), etcdCli)
	assert.Nil(t, err)
	assert.NotNil(t, client)

	err = client.Init()
	assert.Nil(t, err)

	err = client.Start()
	assert.Nil(t, err)

	err = client.Register()
	assert.Nil(t, err)

	checkFunc := func(retNotNil bool) {
		retCheck := func(notNil bool, ret any, err error) {
			if notNil {
				assert.NotNil(t, ret)
				assert.Nil(t, err)
			} else {
				assert.Nil(t, ret)
				assert.NotNil(t, err)
			}
		}

		r1, err := client.GetComponentStates(ctx)
		retCheck(retNotNil, r1, err)

		r2, err := client.GetTimeTickChannel(ctx)
		retCheck(retNotNil, r2, err)

		r3, err := client.GetStatisticsChannel(ctx)
		retCheck(retNotNil, r3, err)

		r4, err := client.ShowCollections(ctx, nil)
		retCheck(retNotNil, r4, err)

		r5, err := client.ShowPartitions(ctx, nil)
		retCheck(retNotNil, r5, err)

		r6, err := client.LoadPartitions(ctx, nil)
		retCheck(retNotNil, r6, err)

		r7, err := client.ReleasePartitions(ctx, nil)
		retCheck(retNotNil, r7, err)

		r8, err := client.ShowCollections(ctx, nil)
		retCheck(retNotNil, r8, err)

		r9, err := client.LoadCollection(ctx, nil)
		retCheck(retNotNil, r9, err)

		r10, err := client.ReleaseCollection(ctx, nil)
		retCheck(retNotNil, r10, err)

		r12, err := client.ShowPartitions(ctx, nil)
		retCheck(retNotNil, r12, err)

		r13, err := client.GetPartitionStates(ctx, nil)
		retCheck(retNotNil, r13, err)

		r14, err := client.GetSegmentInfo(ctx, nil)
		retCheck(retNotNil, r14, err)

		r15, err := client.GetMetrics(ctx, nil)
		retCheck(retNotNil, r15, err)

		r16, err := client.LoadBalance(ctx, nil)
		retCheck(retNotNil, r16, err)

		r17, err := client.GetReplicas(ctx, nil)
		retCheck(retNotNil, r17, err)

		r18, err := client.GetShardLeaders(ctx, nil)
		retCheck(retNotNil, r18, err)

		r19, err := client.ShowConfigurations(ctx, nil)
		retCheck(retNotNil, r19, err)

		r20, err := client.CheckHealth(ctx, nil)
		retCheck(retNotNil, r20, err)
	}

	client.grpcClient = &mock.GRPCClientBase[querypb.QueryCoordClient]{
		GetGrpcClientErr: errors.New("dummy"),
	}

	newFunc1 := func(cc *grpc.ClientConn) querypb.QueryCoordClient {
		return &mock.GrpcQueryCoordClient{Err: nil}
	}
	client.grpcClient.SetNewGrpcClientFunc(newFunc1)

	checkFunc(false)

	client.grpcClient = &mock.GRPCClientBase[querypb.QueryCoordClient]{
		GetGrpcClientErr: nil,
	}

	newFunc2 := func(cc *grpc.ClientConn) querypb.QueryCoordClient {
		return &mock.GrpcQueryCoordClient{Err: errors.New("dummy")}
	}

	client.grpcClient.SetNewGrpcClientFunc(newFunc2)

	checkFunc(false)

	client.grpcClient = &mock.GRPCClientBase[querypb.QueryCoordClient]{
		GetGrpcClientErr: nil,
	}

	newFunc3 := func(cc *grpc.ClientConn) querypb.QueryCoordClient {
		return &mock.GrpcQueryCoordClient{Err: nil}
	}
	client.grpcClient.SetNewGrpcClientFunc(newFunc3)

	checkFunc(true)

	err = client.Stop()
	assert.Nil(t, err)
}
