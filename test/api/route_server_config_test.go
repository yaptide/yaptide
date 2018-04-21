// +build integration

package api

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	mgo "gopkg.in/mgo.v2"
)

var serverConfigTestCasses = []apiTestCase{
	apiTestCase{
		requests: []func(*testing.T, []response) request{
			func(t *testing.T, r []response) request {
				return request{
					method: "GET",
					path:   "/server_configuration",
					body:   nil,
				}
			},
		},
		validate: func(t *testing.T, responses []response, session *mgo.Session) {
			r := responses[0]
			t.Logf("%+v", r)
			body, bodyOk := r.body.(map[string]interface{})
			require.True(t, bodyOk)
			_, materialsOk := body["predefinedMaterials"].([]interface{})
			_, isotopesOk := body["isotopes"].([]interface{})
			_, particlesOk := body["particles"].([]interface{})
			_, scoringTypesOk := body["scoringTypes"].([]interface{})

			assert.True(t, materialsOk)
			assert.True(t, isotopesOk)
			assert.True(t, particlesOk)
			assert.True(t, scoringTypesOk)
			assert.Len(t, body, 4)
		},
	},
}

func TestServerConfig(t *testing.T) {
	runTestCases(t, serverConfigTestCasses)
}
