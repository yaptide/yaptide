package api

import (
	"io/ioutil"
	"net/http"
	"os"
	"testing"

	conf "github.com/yaptide/app/config"
	"github.com/yaptide/app/web"
	"gopkg.in/mgo.v2/dbtest"
)

var DBServer dbtest.DBServer

var Router http.Handler

var log = conf.NamedLogger("test/rest")

// TestMain wraps all tests with the needed initialized mock DB and fixtures
func TestMain(m *testing.M) {
	tempDir, _ := ioutil.TempDir("", "rest_mongo")
	DBServer.SetPath(tempDir)

	session := DBServer.Session()
	router, cleanup, routerErr := web.NewRouter(&conf.Config{}, session)
	if routerErr != nil {
		log.Error(routerErr.Error())
		os.Exit(-1)
	}
	Router = router

	// Run the test suite
	retCode := m.Run()

	cleanup()

	session.DB("").DropDatabase()
	session.Close()

	DBServer.Stop()

	os.Exit(retCode)
}
