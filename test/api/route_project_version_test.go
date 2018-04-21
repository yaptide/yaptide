// +build integration

package api

import (
	"fmt"
	"net/http"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/yaptide/app/model"
	mgo "gopkg.in/mgo.v2"
	"gopkg.in/mgo.v2/bson"
)

var projectVersionTestCasses = []apiTestCase{
	apiTestCase{
		name: "update first version settings",
		requests: []func(*testing.T, []response) request{
			createDefaultUserRequest,
			loginAsDefaultUserRequest,
			createProjectRequest,
			func(t *testing.T, r []response) request {
				return request{
					method: "PUT",
					path: fmt.Sprintf(
						"/versions/%s/%d/settings",
						extractStringFromInterface(t, r[2].body, "id"),
						0,
					),
					body: M{
						"computingLibrary": "shield",
					},
				}
			},
		},
		validate: func(t *testing.T, responses []response, session *mgo.Session) {
			t.Logf("%+v", responses[3])

			assert.Equal(t, http.StatusOK, responses[3].code)

			projectID := extractStringFromInterface(t, responses[2].body, "id")

			var rawProject map[string]interface{}
			require.Nil(t,
				session.DB("").C("project").
					FindId(bson.ObjectIdHex(projectID)).One(&rawProject),
			)
			rawVersions := extractFromMapInterface(t, rawProject, "versions")
			rawVersion := extractFromSliceInterface(t, rawVersions, 0)

			setupID := extractFromMapInterface(t, rawVersion, "setupId")
			resultID := extractFromMapInterface(t, rawVersion, "resultId")

			var setup M
			var result M
			require.Nil(t,
				session.DB("").C("simulationSetup").
					FindId(setupID).One(&setup),
			)
			require.Nil(t,
				session.DB("").C("simulationResult").
					FindId(resultID).One(&result),
			)

			assert.Equal(t, "project name",
				extractStringFromInterface(t, rawProject, "name"),
			)
			assert.Equal(t, "project description",
				extractStringFromInterface(t, rawProject, "description"),
			)

			assert.Equal(t, 2, extractFromMapInterface(t, rawVersion, "status"))
			assert.Equal(t,
				map[string]interface{}{
					"computingLibrary": 1,
				}, extractFromMapInterface(t, rawVersion, "settings"),
			)

			var project model.Project
			require.Nil(t,
				session.DB("").C("project").
					FindId(bson.ObjectIdHex(projectID)).One(&project),
			)
			assert.Equal(t, model.Edited, project.Versions[0].Status)
			assert.Equal(t, model.ShieldLibrary, project.Versions[0].Settings.ComputingLibrary)
		},
	},
	apiTestCase{
		name: "create new version from last when previous is \"edited\"",
		requests: []func(*testing.T, []response) request{
			createDefaultUserRequest,
			loginAsDefaultUserRequest,
			createProjectRequest,
			setVersionLibraryRequestFunc(2, 0),
			func(t *testing.T, r []response) request {
				return request{
					method: "POST",
					path: fmt.Sprintf(
						"/versions/%s",
						extractStringFromInterface(t, r[2].body, "id"),
					),
					body: M{},
				}
			},
		},
		validate: func(t *testing.T, responses []response, session *mgo.Session) {
			t.Logf("%+v", responses[4])
			assert.Equal(t, http.StatusOK, responses[0].code)
			assert.Equal(t, http.StatusOK, responses[1].code)
			assert.Equal(t, http.StatusOK, responses[2].code)
			assert.Equal(t, http.StatusOK, responses[3].code)
			assert.Equal(t, http.StatusOK, responses[4].code)

			// db checks
			projectID := extractStringFromInterface(t, responses[2].body, "id")

			var rawProject map[string]interface{}
			require.Nil(
				t,
				session.DB("").C("project").
					FindId(bson.ObjectIdHex(projectID)).
					One(&rawProject),
			)
			t.Logf("%+v", rawProject)

			var project model.Project
			require.Nil(
				t,
				session.DB("").C("project").
					FindId(bson.ObjectIdHex(projectID)).
					One(&project),
			)
			t.Logf("%+v", project)

			assert.Equal(
				t, "project name",
				extractFromMapInterface(t, rawProject, "name"),
			)
			assert.Equal(
				t, "project description",
				extractFromMapInterface(t, rawProject, "description"),
			)

			rawVersions := extractFromMapInterface(t, rawProject, "versions")
			rawVersion := extractFromSliceInterface(t, rawVersions, 1)
			_ = extractFromMapInterface(t, rawVersion, "settings")
			_ = extractFromMapInterface(t, rawVersion, "status")

			assert.Equal(
				t, model.New, project.Versions[1].Status,
			)
			assert.Equal(
				t, model.ShieldLibrary,
				project.Versions[1].Settings.ComputingLibrary,
			)
		},
	},
}

func TestProjectVersion(t *testing.T) {
	runTestCases(t, projectVersionTestCasses)
}
