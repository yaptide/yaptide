package api

import (
	"regexp"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func assertMongoID(t *testing.T, value interface{}) {
	t.Helper()
	str, ok := value.(string)
	require.True(t, ok)
	assert.Regexp(t, regexp.MustCompile("^[a-fA-F0-9]{24}$"), str)
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
