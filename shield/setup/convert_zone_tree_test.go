package setup

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/yaptide/converter/setup"
	"github.com/yaptide/converter/shield"
)

func TestConvertSetupZonesToZoneTreeForest(t *testing.T) {
	type testCase struct {
		ZoneMap            setup.ZoneMap
		MaterialIDToShield map[setup.ID]shield.MaterialID
		BodyIDToShield     map[setup.ID]shield.BodyID

		Expected      []*zoneTree
		ExpectedError error
	}

	check := func(t *testing.T, tc testCase) {
		t.Helper()

		actual, actualErr := convertSetupZonesToZoneTreeForest(tc.ZoneMap, tc.MaterialIDToShield, tc.BodyIDToShield)

		assert.Equal(t, tc.ExpectedError, actualErr)
		assert.Equal(t, tc.Expected, actual)
	}

	t.Run("SimpleOneZone", func(t *testing.T) {
		check(t, testCase{
			ZoneMap: createZoneMap(&setup.Zone{
				ID:         setup.ID(1),
				ParentID:   setup.ID(0),
				BaseID:     setup.ID(1),
				MaterialID: setup.ID(2),
				Construction: []*setup.Operation{
					&setup.Operation{Type: setup.Intersect, BodyID: setup.ID(100)},
				},
			}),
			BodyIDToShield:     map[setup.ID]shield.BodyID{1: 1, 100: 2},
			MaterialIDToShield: map[setup.ID]shield.MaterialID{2: 200},
			Expected: []*zoneTree{
				&zoneTree{
					childrens:  []*zoneTree{},
					baseBodyID: 1,
					operations: []operation{operation{
						BodyID: 2,
						Type:   setup.Intersect,
					}},
					materialID: 200,
				},
			},
			ExpectedError: nil,
		})
	})

	t.Run("ManyZones", func(t *testing.T) {
		check(t, testCase{
			ZoneMap: createZoneMap(
				&setup.Zone{
					ID:         setup.ID(1),
					ParentID:   setup.ID(0),
					BaseID:     setup.ID(1),
					MaterialID: setup.ID(2),
					Construction: []*setup.Operation{
						&setup.Operation{Type: setup.Intersect, BodyID: setup.ID(100)},
					},
				},
				&setup.Zone{
					ID:         setup.ID(2),
					ParentID:   setup.ID(1),
					BaseID:     setup.ID(300),
					MaterialID: setup.ID(300),
				},
			),
			BodyIDToShield:     map[setup.ID]shield.BodyID{1: 1, 100: 2, 300: 3},
			MaterialIDToShield: map[setup.ID]shield.MaterialID{2: 200, 300: 1},
			Expected: []*zoneTree{
				&zoneTree{
					childrens: []*zoneTree{
						&zoneTree{
							childrens:  []*zoneTree{},
							baseBodyID: 3,
							operations: []operation{},
							materialID: 1,
						},
					},
					baseBodyID: 1,
					operations: []operation{operation{
						BodyID: 2,
						Type:   setup.Intersect,
					}},
					materialID: 200,
				},
			},
			ExpectedError: nil,
		})
	})
}

func createZoneMap(zones ...*setup.Zone) setup.ZoneMap {
	res := setup.ZoneMap{}
	for _, z := range zones {
		res[z.ID] = z
	}
	return res
}
