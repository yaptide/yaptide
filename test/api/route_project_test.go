package api

import (
	"fmt"
	"net/http"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	mgo "gopkg.in/mgo.v2"
)

var projectTestCasses = []apiTestCase{
	apiTestCase{
		name: "get projects from new user [empty list]",
		requests: []func(*testing.T, []response) request{
			createDefaultUserRequest,
			loginAsDefaultUserRequest,
			func(t *testing.T, r []response) request {
				return request{
					method: "GET",
					path:   "/projects",
					body:   nil,
				}
			},
		},
		validate: func(t *testing.T, responses []response, session *mgo.Session) {
			r := responses[2]
			body, bodyOk := r.body.([]interface{})
			statusCode := r.code
			if !bodyOk ||
				len(body) != 0 ||
				statusCode != http.StatusOK {
				t.Fatalf("wrong user data in response %v", r)
			}
		},
	},
	apiTestCase{
		name: "create project",
		requests: []func(*testing.T, []response) request{
			createDefaultUserRequest,
			loginAsDefaultUserRequest,
			func(t *testing.T, r []response) request {
				return request{
					method: "POST",
					path:   "/projects",
					body: map[string]interface{}{
						"name":        "project name",
						"description": "project description",
					},
				}
			},
		},
		validate: func(t *testing.T, responses []response, session *mgo.Session) {
			r := responses[2]
			body, bodyOk := r.body.(map[string]interface{})
			require.True(t, bodyOk)

			assert.Equal(t, r.code, http.StatusOK)

			assert.Equal(t, "project name", body["name"])
			assert.Equal(t, "project description", body["description"])
			assertMongoID(t, body["id"])

			user, userOk := responses[0].body.(map[string]interface{})
			require.True(t, userOk)
			assert.Equal(t, user["id"], body["userId"])

			versions, versionsOk := body["versions"].([]interface{})
			assert.True(t, versionsOk)
			assert.Len(t, versions, 1)

			version, versionOk := versions[0].(map[string]interface{})
			require.True(t, versionOk)
			assert.Equal(t, float64(0), version["id"])
			assert.Equal(t, "new", version["status"])
			assertMongoID(t, version["setupId"])
			assertMongoID(t, version["resultId"])
			assert.NotZero(t, version["updatedAt"])

			versionSettings, setttingsOk := version["settings"].(map[string]interface{})
			require.True(t, setttingsOk)
			assert.Zero(t, versionSettings["computingLibrary"])
			assert.Zero(t, versionSettings["simulationEngine"])
		},
	},
	apiTestCase{
		name: "delete project",
		requests: []func(*testing.T, []response) request{
			createDefaultUserRequest,
			loginAsDefaultUserRequest,
			createProjectRequest,
			func(t *testing.T, r []response) request {
				body, bodyOk := r[2].body.(map[string]interface{})
				require.True(t, bodyOk)
				assert.IsType(t, "", body["id"])
				return request{
					method: "DELETE",
					path:   fmt.Sprintf("/projects/%s", body["id"]),
					body:   nil,
				}
			},
		},
		validate: func(t *testing.T, responses []response, session *mgo.Session) {
			r := responses[3]
			t.Logf("%+v", r)
			body, bodyOk := r.body.(bool)
			assert.True(t, bodyOk)

			assert.Equal(t, http.StatusOK, r.code)
			assert.True(t, body)
		},
	},
	apiTestCase{
		name: "update project",
		requests: []func(*testing.T, []response) request{
			createDefaultUserRequest,
			loginAsDefaultUserRequest,
			createProjectRequest,
			func(t *testing.T, r []response) request {
				body, bodyOk := r[2].body.(map[string]interface{})
				assert.True(t, bodyOk)
				assert.IsType(t, "", body["id"])
				return request{
					method: "PUT",
					path:   fmt.Sprintf("/projects/%s", body["id"]),
					body: map[string]interface{}{
						"name":        "new name",
						"description": "new description",
					},
				}
			},
		},
		validate: func(t *testing.T, responses []response, session *mgo.Session) {
			r := responses[3]
			t.Logf("%+v", r)
			body, bodyOk := r.body.(map[string]interface{})
			require.True(t, bodyOk)

			assert.Equal(t, http.StatusOK, r.code)
			assert.Equal(t, "new name", body["name"])
			assert.Equal(t, "new description", body["description"])
		},
	},
	apiTestCase{
		name: "get projects from user with one project",
		requests: []func(*testing.T, []response) request{
			createDefaultUserRequest,
			loginAsDefaultUserRequest,
			createProjectRequest,
			func(t *testing.T, r []response) request {
				return request{
					method: "GET",
					path:   "/projects",
					body:   nil,
				}
			},
		},
		validate: func(t *testing.T, responses []response, session *mgo.Session) {
			r := responses[3]
			t.Logf("%+v", r)
			body, bodyOk := r.body.([]interface{})
			require.True(t, bodyOk)
			assert.Equal(t, http.StatusOK, r.code)
			assert.Len(t, body, 1)

			item, itemOk := body[0].(map[string]interface{})
			require.True(t, itemOk)

			assert.Equal(t, "project name", item["name"])
			assert.Equal(t, "project description", item["description"])
			assertMongoID(t, item["id"])
		},
	},
	apiTestCase{
		name: "get project by id from user with one project",
		requests: []func(*testing.T, []response) request{
			createDefaultUserRequest,
			loginAsDefaultUserRequest,
			createProjectRequest,
			func(t *testing.T, r []response) request {
				body, bodyOk := r[2].body.(map[string]interface{})
				require.True(t, bodyOk)
				assert.IsType(t, "", body["id"])
				return request{
					method: "GET",
					path:   fmt.Sprintf("/projects/%s", body["id"]),
					body:   nil,
				}
			},
		},
		validate: func(t *testing.T, responses []response, session *mgo.Session) {
			r := responses[3]
			t.Logf("%+v", r)
			assert.Equal(t, http.StatusOK, r.code)
			body, bodyOk := r.body.(map[string]interface{})
			require.True(t, bodyOk)

			assert.Equal(t, "project name", body["name"])
			assert.Equal(t, "project description", body["description"])
			assertMongoID(t, body["id"])
		},
	},
}

func TestProject(t *testing.T) {
	runTestCases(t, projectTestCasses)
}
