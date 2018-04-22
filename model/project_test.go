package model

import (
	"testing"

	"gopkg.in/mgo.v2/bson"

	"github.com/yaptide/yaptide/test"
)

var testCases = test.MarshallingCases{
	{
		&Project{
			ID:     bson.ObjectIdHex("58cfd607dc25403a3b691781"),
			UserID: bson.ObjectIdHex("cccccccccccccccccccccccc"),
			ProjectDetails: ProjectDetails{
				Name:        "name",
				Description: "description",
				Versions:    []Version{},
			},
		},
		`{
			"id": "58cfd607dc25403a3b691781",
			"userId": "cccccccccccccccccccccccc",
			"name": "name",
			"description": "description",
			"versions": []
		}`,
	},
}

var onlyMarshalling = test.MarshallingCases{
	{
		&Version{ID: 1,
			Status:   New,
			Settings: NewSettings(),
			SetupID:  bson.ObjectIdHex("bbbbbbbbbbbbbbbbbbbbbbbb"),
			ResultID: bson.ObjectIdHex("aaaaaaaaaaaaaaaaaaaaaaaa"),
		},
		`{
			"id": 1,
			"status": "new",
			"settings": {
				"simulationEngine": "",
				"computingLibrary": ""
			},
			"setupId": "bbbbbbbbbbbbbbbbbbbbbbbb",
			"resultId": "aaaaaaaaaaaaaaaaaaaaaaaa",
			"updatedAt": "0001-01-01T00:00:00Z"
		}`,
	},
}

func TestMarshal(t *testing.T) {
	test.Marshal(t, testCases)
	test.Marshal(t, onlyMarshalling)
}

func TestUnmarshal(t *testing.T) {
	test.Unmarshal(t, testCases)
}

func TestUnmarshalMarshalled(t *testing.T) {
	test.UnmarshalMarshalled(t, testCases)
}

func TestMarshalUnmarshalled(t *testing.T) {
	test.MarshalUnmarshalled(t, testCases)
}
