package model

import (
	"testing"

	"github.com/yaptide/app/test"

	"gopkg.in/mgo.v2/bson"
)

var userTestCases = test.MarshallingCases{
	{
		&User{ID: bson.ObjectIdHex("58cfd607dc25403a3b691781"), Username: "username", Email: "email", PasswordHash: "password"},
		`{
		    "id": "58cfd607dc25403a3b691781",
		    "username": "username",
		    "email": "email",
		    "password": "password"
		}`,
	},
}

func TestUserMarshal(t *testing.T) {
	test.Marshal(t, userTestCases)
}

func TestUserUnmarshal(t *testing.T) {
	test.Unmarshal(t, userTestCases)
}

func TestUserUnmarshalMarshalled(t *testing.T) {
	test.UnmarshalMarshalled(t, userTestCases)
}

func TestUserMarshalUnmarshalled(t *testing.T) {
	test.MarshalUnmarshalled(t, userTestCases)
}
