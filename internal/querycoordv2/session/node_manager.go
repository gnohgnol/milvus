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

package session

import (
	"sync"

	"github.com/milvus-io/milvus/internal/metrics"
)

type Manager interface {
	Add(node *NodeInfo)
	Remove(nodeID int64)
	Get(nodeID int64) *NodeInfo
	GetAll() []*NodeInfo
}

type NodeManager struct {
	mu    sync.RWMutex
	nodes map[int64]*NodeInfo
}

func (m *NodeManager) Add(node *NodeInfo) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.nodes[node.ID()] = node
	metrics.QueryCoordNumQueryNodes.WithLabelValues().Set(float64(len(m.nodes)))
}

func (m *NodeManager) Remove(nodeID int64) {
	m.mu.Lock()
	defer m.mu.Unlock()
	delete(m.nodes, nodeID)
	metrics.QueryCoordNumQueryNodes.WithLabelValues().Set(float64(len(m.nodes)))
}

func (m *NodeManager) Get(nodeID int64) *NodeInfo {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return m.nodes[nodeID]
}

func (m *NodeManager) GetAll() []*NodeInfo {
	m.mu.RLock()
	defer m.mu.RUnlock()
	ret := make([]*NodeInfo, 0, len(m.nodes))
	for _, n := range m.nodes {
		ret = append(ret, n)
	}
	return ret
}

func NewNodeManager() *NodeManager {
	return &NodeManager{
		nodes: make(map[int64]*NodeInfo),
	}
}

type NodeInfo struct {
	stats
	mu   sync.RWMutex
	id   int64
	addr string
}

func (n *NodeInfo) ID() int64 {
	return n.id
}

func (n *NodeInfo) Addr() string {
	return n.addr
}

func (n *NodeInfo) SegmentCnt() int {
	n.mu.RLock()
	defer n.mu.RUnlock()
	return n.stats.getSegmentCnt()
}

func (n *NodeInfo) ChannelCnt() int {
	n.mu.RLock()
	defer n.mu.RUnlock()
	return n.stats.getChannelCnt()
}

func (n *NodeInfo) UpdateStats(opts ...StatsOption) {
	n.mu.Lock()
	for _, opt := range opts {
		opt(n)
	}
	n.mu.Unlock()
}

func NewNodeInfo(id int64, addr string) *NodeInfo {
	return &NodeInfo{
		stats: newStats(),
		id:    id,
		addr:  addr,
	}
}

type StatsOption func(*NodeInfo)

func WithSegmentCnt(cnt int) StatsOption {
	return func(n *NodeInfo) {
		n.setSegmentCnt(cnt)
	}
}

func WithChannelCnt(cnt int) StatsOption {
	return func(n *NodeInfo) {
		n.setChannelCnt(cnt)
	}
}
