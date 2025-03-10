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

package metrics

import (
	// nolint:gosec
	_ "net/http/pprof"

	"github.com/milvus-io/milvus/internal/management"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

const (
	milvusNamespace = "milvus"

	AbandonLabel = "abandon"
	SuccessLabel = "success"
	FailLabel    = "fail"
	TotalLabel   = "total"

	InsertLabel    = "insert"
	DeleteLabel    = "delete"
	SearchLabel    = "search"
	QueryLabel     = "query"
	CacheHitLabel  = "hit"
	CacheMissLabel = "miss"
	TimetickLabel  = "timetick"
	AllLabel       = "all"

	UnissuedIndexTaskLabel   = "unissued"
	InProgressIndexTaskLabel = "in-progress"
	FinishedIndexTaskLabel   = "finished"
	FailedIndexTaskLabel     = "failed"
	RecycledIndexTaskLabel   = "recycled"

	// Note: below must matchcommonpb.SegmentState_name fields.
	SealedSegmentLabel   = "Sealed"
	GrowingSegmentLabel  = "Growing"
	FlushedSegmentLabel  = "Flushed"
	FlushingSegmentLabel = "Flushing"
	DroppedSegmentLabel  = "Dropped"

	Leader     = "OnLeader"
	FromLeader = "FromLeader"

	nodeIDLabelName          = "node_id"
	statusLabelName          = "status"
	indexTaskStatusLabelName = "index_task_status"
	msgTypeLabelName         = "msg_type"
	collectionIDLabelName    = "collection_id"
	channelNameLabelName     = "channel_name"
	functionLabelName        = "function_name"
	queryTypeLabelName       = "query_type"
	collectionName           = "collection_name"
	segmentStateLabelName    = "segment_state"
	usernameLabelName        = "username"
	roleNameLabelName        = "role_name"
	cacheNameLabelName       = "cache_name"
	cacheStateLabelName      = "cache_state"
	requestScope             = "scope"
)

var (
	// buckets involves durations in milliseconds,
	// [1 2 4 8 16 32 64 128 256 512 1024 2048 4096 8192 16384 32768 65536 1.31072e+05]
	buckets = prometheus.ExponentialBuckets(1, 2, 18)
)

// Register serves prometheus http service
func Register(r *prometheus.Registry) {
	management.Register(&management.HTTPHandler{
		Path:    "/metrics",
		Handler: promhttp.HandlerFor(r, promhttp.HandlerOpts{}),
	})
	management.Register(&management.HTTPHandler{
		Path:    "/metrics_default",
		Handler: promhttp.Handler(),
	})
}
