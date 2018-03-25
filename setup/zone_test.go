package setup

import (
	"testing"

	test "github.com/yaptide/converter/test"
)

var zoneTestCases = test.MarshallingCases{
	{
		&Zone{
			ID:         ID(1),
			ParentID:   ID(0),
			Name:       "name",
			BaseID:     ID(1),
			MaterialID: ID(2),
			Construction: []*Operation{
				&Operation{Type: Intersect, BodyID: ID(100)},
			},
		},
		`{
			"id": 1,
			"parentId": 0,
			"name": "name",
			"baseId": 1,
			"materialId": 2,
			"construction": [
				{
					"bodyId": 100,
					"type": "intersect"
				}
			]
		}`,
	},

	{
		&Zone{
			ID:         ID(2),
			ParentID:   ID(1),
			Name:       "name",
			BaseID:     ID(1),
			MaterialID: ID(2),
			Construction: []*Operation{
				&Operation{Type: Intersect, BodyID: ID(100)},
				&Operation{Type: Subtract, BodyID: ID(200)},
				&Operation{Type: Union, BodyID: ID(300)},
			},
		},
		`{
			"id": 2,
			"parentId": 1,
			"name": "name",
			"baseId": 1,
			"materialId": 2,
			"construction": [
				{
					"bodyId": 100,
					"type": "intersect"
				},
				{
					"bodyId": 200,
					"type": "subtract"
				},
				{
					"bodyId": 300,
					"type": "union"
				}
			]
		}`,
	},
}

func TestZoneMarshal(t *testing.T) {
	test.Marshal(t, zoneTestCases)
}

func TestZoneUnmarshal(t *testing.T) {
	test.Unmarshal(t, zoneTestCases)
}

func TestZoneMarshalUnmarshalled(t *testing.T) {
	test.MarshalUnmarshalled(t, zoneTestCases)
}

func TestZoneUnmarshalMarshalled(t *testing.T) {
	test.UnmarshalMarshalled(t, zoneTestCases)
}
