// +build integration

package api

import (
	"net/http"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	mgo "gopkg.in/mgo.v2"
)

var userLoginTestCasses = []apiTestCase{
	apiTestCase{
		requests: []func(*testing.T, []response) request{
			createDefaultUserRequest,
			func(t *testing.T, r []response) request {
				return request{
					method: "POST",
					path:   "/auth/login",
					body: map[string]interface{}{
						"username": "username",
						"password": "password",
					},
				}
			},
		},
		validate: func(t *testing.T, responses []response, session *mgo.Session) {
			r := responses[1]
			body, bodyOk := r.body.(map[string]interface{})
			require.True(t, bodyOk)
			user, userOk := body["user"].(map[string]interface{})
			require.True(t, userOk)
			assert.Equal(t, http.StatusOK, r.code)

			assert.Equal(t, "username", user["username"])
			assert.Equal(t, "email", user["email"])
			assertMongoID(t, user["id"])
		},
	},
}

func TestUserLogin(t *testing.T) {
	runTestCases(t, userLoginTestCasses)
}
