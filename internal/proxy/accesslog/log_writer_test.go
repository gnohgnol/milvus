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

package accesslog

import (
	"os"
	"path"
	"testing"
	"time"

	"github.com/milvus-io/milvus/internal/util/paramtable"
	"github.com/stretchr/testify/assert"
)

func getText(size int) []byte {
	var text = make([]byte, size)

	for i := 0; i < size; i++ {
		text[i] = byte('-')
	}
	return text
}
func TestRotateLogger_Basic(t *testing.T) {
	var Params paramtable.ComponentParam
	Params.Init()
	testPath := "/tmp/accesstest"
	Params.ProxyCfg.AccessLog.LocalPath = testPath
	Params.ProxyCfg.AccessLog.MinioEnable = true
	Params.ProxyCfg.AccessLog.RemotePath = "access_log/"
	defer os.RemoveAll(testPath)

	logger, err := NewRotateLogger(&Params.ProxyCfg.AccessLog, &Params.MinioCfg)
	assert.NoError(t, err)
	defer logger.handler.Clean()
	defer logger.Close()

	num := 100
	text := getText(num)
	n, err := logger.Write(text)
	assert.Equal(t, num, n)
	assert.NoError(t, err)

	err = logger.Rotate()
	assert.NoError(t, err)

	time.Sleep(time.Duration(1) * time.Second)
	logfiles, err := logger.handler.listAll()
	assert.NoError(t, err)
	assert.Equal(t, 1, len(logfiles))
}

func TestRotateLogger_TimeRotate(t *testing.T) {
	var Params paramtable.ComponentParam
	Params.Init()
	testPath := "/tmp/accesstest"
	Params.ProxyCfg.AccessLog.LocalPath = testPath
	Params.ProxyCfg.AccessLog.MinioEnable = true
	Params.ProxyCfg.AccessLog.RemotePath = "access_log/"
	Params.ProxyCfg.AccessLog.RotatedTime = 2
	//close file retention
	Params.ProxyCfg.AccessLog.MaxBackups = 0
	defer os.RemoveAll(testPath)

	logger, err := NewRotateLogger(&Params.ProxyCfg.AccessLog, &Params.MinioCfg)
	assert.NoError(t, err)
	defer logger.handler.Clean()
	defer logger.Close()

	num := 100
	text := getText(num)
	n, err := logger.Write(text)
	assert.Equal(t, num, n)
	assert.NoError(t, err)

	time.Sleep(time.Duration(4) * time.Second)
	logfiles, err := logger.handler.listAll()
	assert.NoError(t, err)
	assert.GreaterOrEqual(t, len(logfiles), 1)
}

func TestRotateLogger_SizeRotate(t *testing.T) {
	var Params paramtable.ComponentParam
	Params.Init()
	testPath := "/tmp/accesstest"
	Params.ProxyCfg.AccessLog.LocalPath = testPath
	Params.ProxyCfg.AccessLog.MinioEnable = true
	Params.ProxyCfg.AccessLog.RemotePath = "access_log/"
	Params.ProxyCfg.AccessLog.MaxSize = 1
	defer os.RemoveAll(testPath)

	logger, err := NewRotateLogger(&Params.ProxyCfg.AccessLog, &Params.MinioCfg)
	assert.NoError(t, err)
	defer logger.handler.Clean()
	defer logger.Close()

	num := 1024 * 1024
	text := getText(num + 1)
	_, err = logger.Write(text)
	assert.Error(t, err)

	for i := 1; i <= 2; i++ {
		text = getText(num)
		n, err := logger.Write(text)
		assert.Equal(t, num, n)
		assert.NoError(t, err)
	}

	time.Sleep(time.Duration(1) * time.Second)
	logfiles, err := logger.handler.listAll()
	assert.NoError(t, err)
	assert.Equal(t, 1, len(logfiles))
}

func TestRotateLogger_LocalRetention(t *testing.T) {
	var Params paramtable.ComponentParam
	Params.Init()
	testPath := "/tmp/accesstest"
	Params.ProxyCfg.AccessLog.LocalPath = testPath
	Params.ProxyCfg.AccessLog.MaxBackups = 1
	defer os.RemoveAll(testPath)

	logger, err := NewRotateLogger(&Params.ProxyCfg.AccessLog, &Params.MinioCfg)
	assert.NoError(t, err)
	defer logger.Close()

	logger.Rotate()
	logger.Rotate()
	time.Sleep(time.Duration(1) * time.Second)
	logFiles, err := logger.oldLogFiles()
	assert.NoError(t, err)
	assert.Equal(t, 1, len(logFiles))

}

func TestRotateLogger_BasicError(t *testing.T) {
	var Params paramtable.ComponentParam
	Params.Init()
	testPath := ""
	Params.ProxyCfg.AccessLog.LocalPath = testPath

	logger, err := NewRotateLogger(&Params.ProxyCfg.AccessLog, &Params.MinioCfg)
	assert.NoError(t, err)
	defer os.RemoveAll(logger.dir())
	defer logger.Close()

	logger.openFileExistingOrNew()

	os.Mkdir(path.Join(logger.dir(), "test"), 0744)
	logfile, err := logger.oldLogFiles()
	assert.NoError(t, err)
	assert.Equal(t, 0, len(logfile))

	_, err = logger.timeFromName("a.b", "a", "c")
	assert.Error(t, err)
	_, err = logger.timeFromName("a.b", "d", "c")
	assert.Error(t, err)
}

func TestRotateLogger_InitError(t *testing.T) {
	var params paramtable.ComponentParam
	params.Init()
	testPath := ""
	params.ProxyCfg.AccessLog.LocalPath = testPath
	params.ProxyCfg.AccessLog.MinioEnable = true
	params.Save(params.MinioCfg.Address.Key, "")
	//init err with invalid minio address
	_, err := NewRotateLogger(&params.ProxyCfg.AccessLog, &params.MinioCfg)
	assert.Error(t, err)
}
