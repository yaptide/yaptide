package geometry

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/yaptide/converter"
	"github.com/yaptide/converter/setup"
	"github.com/yaptide/converter/shield/material"
)

func TestConvertSetupZonesToZoneTreeForest(t *testing.T) {
	type testCase struct {
		ZoneMap            converter.ZoneMap
		MaterialIDToShield map[setup.MaterialID]material.ShieldID
		BodyIDToShield     map[setup.BodyID]ShieldBodyID

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
			ZoneMap: createZoneMap(setup.Zone{
				ID:         setup.ZoneID(1),
				ParentID:   setup.ZoneID(0),
				BaseID:     setup.BodyID(1),
				MaterialID: setup.MaterialID(2),
				Construction: []*setup.ZoneOperation{
					&setup.ZoneOperation{Type: setup.Intersect, BodyID: setup.BodyID(100)},
				},
			}),
			BodyIDToShield:     map[setup.BodyID]ShieldBodyID{1: 1, 100: 2},
			MaterialIDToShield: map[setup.MaterialID]material.ShieldID{2: 200},
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
				setup.Zone{
					ID:         setup.ZoneID(1),
					ParentID:   setup.ZoneID(0),
					BaseID:     setup.BodyID(1),
					MaterialID: setup.MaterialID(2),
					Construction: []*setup.ZoneOperation{
						&setup.ZoneOperation{Type: setup.Intersect, BodyID: setup.BodyID(100)},
					},
				},
				setup.Zone{
					ID:         setup.ZoneID(2),
					ParentID:   setup.ZoneID(1),
					BaseID:     setup.BodyID(300),
					MaterialID: setup.MaterialID(300),
				},
			),
			BodyIDToShield:     map[setup.BodyID]ShieldBodyID{1: 1, 100: 2, 300: 3},
			MaterialIDToShield: map[setup.MaterialID]material.ShieldID{2: 200, 300: 1},
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

func createZoneMap(zones ...setup.Zone) converter.ZoneMap {
	res := converter.ZoneMap{}
	for _, z := range zones {
		res[z.ID] = z
	}
	return res
}
