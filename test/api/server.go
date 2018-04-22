package api

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"testing"

	conf "github.com/yaptide/yaptide/config"
	"github.com/yaptide/yaptide/web"
	mgo "gopkg.in/mgo.v2"
	"gopkg.in/mgo.v2/dbtest"
)

// DBServer ....
var dbServer dbtest.DBServer

// Router ...
var router http.Handler

var log = conf.NamedLogger("test/rest")

type request struct {
	method         string
	path           string
	body           map[string]interface{}
	isLoginRequest bool
}

type response struct {
	code int
	body interface{}
}

type apiTestCase struct {
	name     string
	requests []func(*testing.T, []response) request

	validate func(t *testing.T, statusCodes []response, session *mgo.Session)
}

func runTestCases(t *testing.T, cases []apiTestCase) {
	for _, test := range cases {
		log.Infof("start test %s", test.name)
		t.Run(test.name, func(t *testing.T) {
			runTestCase(t, test)
		})
	}
}

func runTestCase(t *testing.T, c apiTestCase) {
	session, router, cleanup := setupTest()
	defer cleanup()

	sessionToken := ""
	responses := make([]response, len(c.requests))
	requestsList := make([]request, len(c.requests))
	for i, resolveRequest := range c.requests {
		requestData := resolveRequest(t, responses)
		requestsList[i] = requestData

		httpReq, httpReqErr := createRequest(t, requestData, sessionToken)
		if httpReqErr != nil {
			t.Fatalf(
				"Create request failed for %s\nerror: %v\nprevious requests: %+v\n previous responses %+v",
				c.name, httpReqErr, requestsList[0:i], responses[0:i],
			)
		}

		responseWriter := httptest.NewRecorder()
		router.ServeHTTP(responseWriter, httpReq)

		var body interface{}
		err := json.Unmarshal(responseWriter.Body.Bytes(), &body)
		if err != nil {
			t.Fatalf(
				"Read request body failed for %s\nerror: %v\nstatusCode: %d body: %s\nprevious requests: %+v\n previous responses %+v",
				c.name, err, responseWriter.Code, responseWriter.Body.String(), requestsList[0:i], responses[0:i],
			)
		}
		responses[i].code = responseWriter.Code
		responses[i].body = body
		if requestData.isLoginRequest {
			if token, ok := body.(map[string]interface{})["token"]; ok {
				sessionToken = token.(string)
			}
		}
	}

	printEntireDB(t, session)
	c.validate(t, responses, session)
}

func createRequest(t *testing.T, r request, token string) (*http.Request, error) {
	t.Helper()
	bodyBytes, marshallErr := json.Marshal(r.body)
	if marshallErr != nil {
		return nil, marshallErr
	}
	req, err := http.NewRequest(
		r.method,
		(&url.URL{Path: r.path}).String(),
		bytes.NewReader(bodyBytes),
	)
	if err != nil {
		return nil, err
	}
	log.Info(token)
	req.Header.Add("X-Auth-Token", token)
	return req, nil
}

func setupTest() (*mgo.Session, http.Handler, func()) {
	dbServer.Wipe()
	session := dbServer.Session()

	router, cleanup, routerErr := web.NewRouter(&conf.Config{}, session)
	if routerErr != nil {
		log.Error(routerErr.Error())
		os.Exit(-1)
	}

	return session, router, func() {
		session.Close()
		cleanup()
	}
}
