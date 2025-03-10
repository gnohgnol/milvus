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

package querynode

import (
	"context"
	"fmt"
	"sync"

	"go.uber.org/zap"

	"github.com/milvus-io/milvus/internal/log"
	"github.com/milvus-io/milvus/internal/metrics"
	"github.com/milvus-io/milvus/internal/mq/msgstream"
	"github.com/milvus-io/milvus/internal/util/funcutil"
	"github.com/milvus-io/milvus/internal/util/paramtable"
)

// dataSyncService manages a lot of flow graphs
type dataSyncService struct {
	ctx context.Context

	mu                     sync.Mutex // guards FlowGraphs
	dmlChannel2FlowGraph   map[Channel]*queryNodeFlowGraph
	deltaChannel2FlowGraph map[Channel]*queryNodeFlowGraph

	metaReplica  ReplicaInterface
	tSafeReplica TSafeReplicaInterface
	msFactory    msgstream.Factory
}

// getFlowGraphNum returns number of flow graphs of dataSyncService.
func (dsService *dataSyncService) getFlowGraphNum() int {
	dsService.mu.Lock()
	defer dsService.mu.Unlock()
	return len(dsService.dmlChannel2FlowGraph) + len(dsService.deltaChannel2FlowGraph)
}

// addFlowGraphsForDMLChannels add flowGraphs to dmlChannel2FlowGraph
func (dsService *dataSyncService) addFlowGraphsForDMLChannels(collectionID UniqueID, dmlChannels []string) (map[string]*queryNodeFlowGraph, error) {
	dsService.mu.Lock()
	defer dsService.mu.Unlock()

	_, err := dsService.metaReplica.getCollectionByID(collectionID)
	if err != nil {
		return nil, err
	}

	results := make(map[string]*queryNodeFlowGraph)
	for _, channel := range dmlChannels {
		if _, ok := dsService.dmlChannel2FlowGraph[channel]; ok {
			log.Warn("dml flow graph has been existed",
				zap.Any("collectionID", collectionID),
				zap.Any("channel", channel),
			)
			continue
		}
		newFlowGraph, err := newQueryNodeFlowGraph(dsService.ctx,
			collectionID,
			dsService.metaReplica,
			dsService.tSafeReplica,
			channel,
			dsService.msFactory)
		if err != nil {
			for _, fg := range results {
				fg.flowGraph.Close()
			}
			return nil, err
		}
		results[channel] = newFlowGraph
	}

	for channel, fg := range results {
		dsService.dmlChannel2FlowGraph[channel] = fg
		log.Info("add DML flow graph",
			zap.Any("collectionID", collectionID),
			zap.Any("channel", channel))
		metrics.QueryNodeNumFlowGraphs.WithLabelValues(fmt.Sprint(paramtable.GetNodeID())).Inc()
	}

	return results, nil
}

// addFlowGraphsForDeltaChannels add flowGraphs to deltaChannel2FlowGraph
func (dsService *dataSyncService) addFlowGraphsForDeltaChannels(collectionID UniqueID, deltaChannels []string, VPDeltaChannels map[string]string) (map[string]*queryNodeFlowGraph, error) {
	log := log.With(
		zap.Int64("collectionID", collectionID),
		zap.Strings("deltaChannels", deltaChannels),
	)

	dsService.mu.Lock()
	defer dsService.mu.Unlock()

	coll, err := dsService.metaReplica.getCollectionByID(collectionID)
	if err != nil {
		return nil, err
	}
	// filter out duplicated channels
	vDeltaChannels := coll.AddVDeltaChannels(deltaChannels, VPDeltaChannels)
	if len(vDeltaChannels) == 0 {
		return map[string]*queryNodeFlowGraph{}, nil
	}

	results := make(map[string]*queryNodeFlowGraph)
	for _, channel := range vDeltaChannels {
		if _, ok := dsService.deltaChannel2FlowGraph[channel]; ok {
			log.Warn("delta flow graph has been existed",
				zap.String("channel", channel),
			)
			continue
		}
		newFlowGraph, err := newQueryNodeDeltaFlowGraph(dsService.ctx,
			collectionID,
			dsService.metaReplica,
			dsService.tSafeReplica,
			channel,
			dsService.msFactory)
		if err != nil {
			for channel, fg := range results {
				fg.flowGraph.Close()
				coll.removeVDeltaChannel(channel)
			}
			return nil, err
		}
		results[channel] = newFlowGraph
	}

	for channel, fg := range results {
		dsService.deltaChannel2FlowGraph[channel] = fg
		log.Info("add delta flow graph",
			zap.String("channel", channel),
		)
		metrics.QueryNodeNumFlowGraphs.WithLabelValues(fmt.Sprint(paramtable.GetNodeID())).Inc()
	}

	return results, nil
}

// getFlowGraphByDMLChannel returns the DML flowGraph by channel
func (dsService *dataSyncService) getFlowGraphByDMLChannel(collectionID UniqueID, channel Channel) (*queryNodeFlowGraph, error) {
	dsService.mu.Lock()
	defer dsService.mu.Unlock()

	if _, ok := dsService.dmlChannel2FlowGraph[channel]; !ok {
		return nil, fmt.Errorf("DML flow graph doesn't existed, collectionID = %d", collectionID)
	}

	// TODO: return clone?
	return dsService.dmlChannel2FlowGraph[channel], nil
}

// getFlowGraphByDeltaChannel returns the delta flowGraph by channel
func (dsService *dataSyncService) getFlowGraphByDeltaChannel(collectionID UniqueID, channel Channel) (*queryNodeFlowGraph, error) {
	dsService.mu.Lock()
	defer dsService.mu.Unlock()

	if _, ok := dsService.deltaChannel2FlowGraph[channel]; !ok {
		return nil, fmt.Errorf("delta flow graph doesn't existed, collectionID = %d", collectionID)
	}

	// TODO: return clone?
	return dsService.deltaChannel2FlowGraph[channel], nil
}

// startFlowGraphByDMLChannel starts the DML flow graph by channel
func (dsService *dataSyncService) startFlowGraphByDMLChannel(collectionID UniqueID, channel Channel) error {
	dsService.mu.Lock()
	defer dsService.mu.Unlock()

	if _, ok := dsService.dmlChannel2FlowGraph[channel]; !ok {
		return fmt.Errorf("DML flow graph doesn't existed, collectionID = %d", collectionID)
	}
	log.Info("start DML flow graph",
		zap.Any("collectionID", collectionID),
		zap.Any("channel", channel),
	)
	dsService.dmlChannel2FlowGraph[channel].flowGraph.Start()
	return nil
}

// startFlowGraphForDeltaChannel would start the delta flow graph by channel
func (dsService *dataSyncService) startFlowGraphForDeltaChannel(collectionID UniqueID, channel Channel) error {
	dsService.mu.Lock()
	defer dsService.mu.Unlock()

	if _, ok := dsService.deltaChannel2FlowGraph[channel]; !ok {
		return fmt.Errorf("delta flow graph doesn't existed, collectionID = %d", collectionID)
	}
	log.Info("start delta flow graph",
		zap.Any("collectionID", collectionID),
		zap.Any("channel", channel),
	)
	dsService.deltaChannel2FlowGraph[channel].flowGraph.Start()
	return nil
}

// removeFlowGraphsByDMLChannels would remove the DML flow graphs by channels
func (dsService *dataSyncService) removeFlowGraphsByDMLChannels(channels []Channel) {
	dsService.mu.Lock()
	defer dsService.mu.Unlock()

	for _, channel := range channels {
		if _, ok := dsService.dmlChannel2FlowGraph[channel]; ok {
			// close flow graph
			dsService.dmlChannel2FlowGraph[channel].close()
			metrics.QueryNodeNumFlowGraphs.WithLabelValues(fmt.Sprint(paramtable.GetNodeID())).Dec()
		}
		delete(dsService.dmlChannel2FlowGraph, channel)
		rateCol.removeTSafeChannel(channel)
	}
}

// removeFlowGraphsByDeltaChannels would remove the delta flow graphs by channels
func (dsService *dataSyncService) removeFlowGraphsByDeltaChannels(channels []Channel) {
	dsService.mu.Lock()
	defer dsService.mu.Unlock()

	for _, channel := range channels {
		if _, ok := dsService.deltaChannel2FlowGraph[channel]; ok {
			// close flow graph
			dsService.deltaChannel2FlowGraph[channel].close()
			metrics.QueryNodeNumFlowGraphs.WithLabelValues(fmt.Sprint(paramtable.GetNodeID())).Dec()
		}
		delete(dsService.deltaChannel2FlowGraph, channel)
		rateCol.removeTSafeChannel(channel)
	}
}

// removeEmptyFlowGraphByChannel would remove delta flow graph if no seal segment exists in meta.
// *segment shall be added into meta before add flow graph
// *release sealed segment shall always come after load completed
func (dsService *dataSyncService) removeEmptyFlowGraphByChannel(collectionID int64, channel string) {
	log := log.With(
		zap.Int64("collectionID", collectionID),
		zap.String("channel", channel),
	)
	dsService.mu.Lock()
	defer dsService.mu.Unlock()

	// convert dml channel name to delta channel name
	dc, err := funcutil.ConvertChannelName(channel, Params.CommonCfg.RootCoordDml, Params.CommonCfg.RootCoordDelta)
	if err != nil {
		log.Warn("removeEmptyFGByDelta failed to convert channel to delta", zap.Error(err))
		return
	}

	// check flow graph exists first
	fg, ok := dsService.deltaChannel2FlowGraph[dc]
	if !ok {
		log.Warn("remove delta flowgraph does not exist")
		return
	}

	// get all sealed segments associated with this channel
	segments, err := dsService.metaReplica.getSegmentIDsByVChannel(nil, channel, segmentTypeSealed)
	if err != nil {
		log.Warn("removeEmptyFGByDelta failed to check segments with VChannel", zap.Error(err))
	}

	// check whether there are still not released segments
	if len(segments) > 0 {
		return
	}

	// start to release flow graph
	log.Info("all segments released, start to remove deltaChannel flowgraph")
	delete(dsService.deltaChannel2FlowGraph, dc)
	dsService.metaReplica.removeCollectionVDeltaChannel(collectionID, dc)
	// close flowgraph first, so no write will be dispatched to tSafeReplica
	fg.close()
	dsService.tSafeReplica.removeTSafe(dc)
	// try best to remove, it's ok if all info is gone before this call
	rateCol.removeTSafeChannel(dc)
}

// newDataSyncService returns a new dataSyncService
func newDataSyncService(ctx context.Context,
	metaReplica ReplicaInterface,
	tSafeReplica TSafeReplicaInterface,
	factory msgstream.Factory) *dataSyncService {

	return &dataSyncService{
		ctx:                    ctx,
		dmlChannel2FlowGraph:   make(map[Channel]*queryNodeFlowGraph),
		deltaChannel2FlowGraph: make(map[Channel]*queryNodeFlowGraph),
		metaReplica:            metaReplica,
		tSafeReplica:           tSafeReplica,
		msFactory:              factory,
	}
}

// close would close and remove all flow graphs in dataSyncService
func (dsService *dataSyncService) close() {
	// close DML flow graphs
	for channel, nodeFG := range dsService.dmlChannel2FlowGraph {
		if nodeFG != nil {
			nodeFG.flowGraph.Close()
		}
		delete(dsService.dmlChannel2FlowGraph, channel)
	}
	// close delta flow graphs
	for channel, nodeFG := range dsService.deltaChannel2FlowGraph {
		if nodeFG != nil {
			nodeFG.flowGraph.Close()
		}
		delete(dsService.deltaChannel2FlowGraph, channel)
	}
}
