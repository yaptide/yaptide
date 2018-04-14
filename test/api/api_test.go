package api

import (
	"io/ioutil"
	"os"
	"testing"
)

// TestMain wraps all tests with the needed initialized mock DB and fixtures
func TestMain(m *testing.M) {
	tempDir, _ := ioutil.TempDir("", "rest_mongo")
	dbServer.SetPath(tempDir)

	retCode := m.Run()

	dbServer.Stop()

	os.Exit(retCode)
}
