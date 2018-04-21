package api

import (
	"fmt"
	"regexp"
	"testing"

	"github.com/davecgh/go-spew/spew"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	mgo "gopkg.in/mgo.v2"
)

type M map[string]interface{}

func extractStringFromInterface(t *testing.T, object interface{}, field string) string {
	t.Helper()
	value, ok := object.(map[string]interface{})
	require.True(t, ok)
	element, ok := value[field]
	require.True(t, ok)
	str, isString := element.(string)
	require.True(t, isString)
	return str
}

func extractFromMapInterface(t *testing.T, object interface{}, field string) interface{} {
	t.Helper()
	value, ok := object.(map[string]interface{})
	require.True(t, ok)
	element, ok := value[field]
	require.True(t, ok)
	return element
}

func extractFromSliceInterface(t *testing.T, object interface{}, index int) interface{} {
	t.Helper()
	slice, ok := object.([]interface{})
	require.True(t, ok)
	require.Len(t, slice, index+1)
	return slice[index]
}

func assertMongoID(t *testing.T, value interface{}) {
	t.Helper()
	str, ok := value.(string)
	require.True(t, ok)
	assert.Regexp(t, regexp.MustCompile("^[a-fA-F0-9]{24}$"), str)
}

func printEntireDB(t *testing.T, session *mgo.Session) {
	var users []interface{}
	var projects []interface{}
	var setups []interface{}
	var results []interface{}

	require.Nil(t, session.DB("").C("user").Find(M{}).All(&users))
	require.Nil(t, session.DB("").C("project").Find(M{}).All(&projects))
	require.Nil(t, session.DB("").C("simulationSetup").Find(M{}).All(&setups))
	require.Nil(t, session.DB("").C("simulationResult").Find(M{}).All(&results))
	t.Logf("users :\n%s", spew.Sdump(users))
	t.Logf("projects :\n%s", spew.Sdump(projects))
	t.Logf("simulation setups :\n%s", spew.Sdump(setups))
	t.Logf("simulation results :\n%s", spew.Sdump(results))
}

var defaultUserInput = map[string]interface{}{
	"username": "username",
	"password": "password",
	"email":    "email",
}

func createDefaultUserRequest(t *testing.T, responses []response) request {
	return request{
		method: "POST",
		path:   "/auth/register",
		body:   defaultUserInput,
	}
}

var defaultUserLoginInput = map[string]interface{}{
	"username": "username",
	"password": "password",
}

func loginAsDefaultUserRequest(t *testing.T, responses []response) request {
	return request{
		method:         "POST",
		path:           "/auth/login",
		body:           defaultUserLoginInput,
		isLoginRequest: true,
	}
}

var defaultProjectInput = map[string]interface{}{
	"name":        "project name",
	"description": "project description",
}

func createProjectRequest(t *testing.T, responses []response) request {
	return request{
		method: "POST",
		path:   "/projects",
		body:   defaultProjectInput,
	}
}

func getProjectRequestFunc(requestNumber int) func(*testing.T, []response) request {
	return func(t *testing.T, r []response) request {
		return request{
			method: "GET",
			path: fmt.Sprintf(
				"/projects/%s",
				extractStringFromInterface(t, r[requestNumber].body, "id"),
			),
			body: nil,
		}
	}
}

func setVersionLibraryRequestFunc(requestNumber int, versionId int) func(*testing.T, []response) request {
	return func(t *testing.T, r []response) request {
		return request{
			method: "PUT",
			path: fmt.Sprintf("/versions/%s/%d/settings",
				extractStringFromInterface(t, r[requestNumber].body, "id"),
				versionId,
			),
			body: map[string]interface{}{
				"computingLibrary": "shield",
			},
		}
	}
}

func createVersionFormLates(requestNumber int) func(*testing.T, []response) request {
	return func(t *testing.T, r []response) request {
		return request{
			method: "POST",
			path: fmt.Sprintf(
				"/versions/%s",
				extractStringFromInterface(t, r[requestNumber].body, "id"),
			),
			body: M{},
		}
	}
}
