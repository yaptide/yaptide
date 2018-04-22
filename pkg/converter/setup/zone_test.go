package setup

import (
	"testing"

	test "github.com/yaptide/yaptide/pkg/converter/test"
)

var zoneTestCases = test.MarshallingCases{
	{
		&Zone{
			ID:         ZoneID(1),
			ParentID:   ZoneID(0),
			Name:       "name",
			BaseID:     BodyID(1),
			MaterialID: MaterialID(2),
			Construction: []*ZoneOperation{
				&ZoneOperation{Type: Intersect, BodyID: BodyID(100)},
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
			ID:         ZoneID(2),
			ParentID:   ZoneID(1),
			Name:       "name",
			BaseID:     BodyID(1),
			MaterialID: MaterialID(2),
			Construction: []*ZoneOperation{
				&ZoneOperation{Type: Intersect, BodyID: BodyID(100)},
				&ZoneOperation{Type: Subtract, BodyID: BodyID(200)},
				&ZoneOperation{Type: Union, BodyID: BodyID(300)},
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
