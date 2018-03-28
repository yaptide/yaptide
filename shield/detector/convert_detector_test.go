package detector

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/yaptide/converter"
	"github.com/yaptide/converter/common"
	"github.com/yaptide/converter/setup"
	"github.com/yaptide/converter/shield/material"
)

func TestConvertSetupDetectors(t *testing.T) {
	type testCase struct {
		Input              converter.DetectorMap
		MaterialIDToShield map[setup.MaterialID]material.ShieldID
		Expected           []Detector
		ExpectedSimContext map[string]setup.DetectorID
	}

	check := func(t *testing.T, tc testCase) {
		t.Helper()

		actual, mapping, actualErr := ConvertSetupDetectors(tc.Input, tc.MaterialIDToShield)

		assert.Equal(t, nil, actualErr)
		assert.Equal(t, tc.Expected, actual)
		assert.Equal(t, tc.ExpectedSimContext, mapping)
	}

	t.Run("One detector", func(t *testing.T) {
		check(t, testCase{
			Input: converter.DetectorMap{5: setup.Detector{
				ID:   5,
				Name: "Ala ma psa",
				DetectorGeometry: setup.DetectorCylinder{
					Radius: common.Range{Min: 0.0, Max: 10.0},
					Angle:  common.Range{Min: -10.0, Max: 20.0},
					ZValue: common.Range{Min: -20.0, Max: 30.0},
					Slices: common.Vec3DCylindricalInt{Radius: 10, Angle: 200, Z: 1000},
				},
				ScoredParticle: common.PredefinedParticle("all"),
				ScoringType:    setup.PredefinedScoring("energy"),
			}},
			MaterialIDToShield: map[setup.MaterialID]material.ShieldID{},
			Expected: []Detector{
				Detector{
					ScoringType: "CYL",
					Arguments: []interface{}{
						0.0, -10.0, -20.0, 10.0, 20.0, 30.0,
						int64(10), int64(200), int64(1000), int64(-1), "ENERGY", "ala_ma_psa0",
					},
				},
			},
			ExpectedSimContext: map[string]setup.DetectorID{
				"ala_ma_psa0": 5,
			},
		})
	})

	t.Run("All combined", func(t *testing.T) {
		check(t, testCase{
			Input: converter.DetectorMap{
				3: setup.Detector{
					ID:   3,
					Name: "raz raz raz",
					DetectorGeometry: setup.DetectorMesh{
						Center: common.Point{X: 0.0, Y: 0.0, Z: 15.0},
						Size:   common.Vec3D{X: 10.0, Y: 10.0, Z: 30.0},
						Slices: common.Vec3DInt{X: 1, Y: 1, Z: 300},
					},

					ScoredParticle: common.HeavyIon{Charge: 10, NucleonsCount: 20},
					ScoringType:    setup.PredefinedScoring("counter"),
				},
				2: setup.Detector{
					ID:   2,
					Name: "dwa dwa dwa",
					DetectorGeometry: setup.DetectorCylinder{
						Radius: common.Range{Min: 0.0, Max: 10.0},
						Angle:  common.Range{Min: -10.0, Max: 20.0},
						ZValue: common.Range{Min: -20.0, Max: 30.0},
						Slices: common.Vec3DCylindricalInt{Radius: 10, Angle: 200, Z: 1000},
					},
					ScoredParticle: common.PredefinedParticle("all"),
					ScoringType:    setup.PredefinedScoring("energy"),
				},
				1: setup.Detector{
					ID:   1,
					Name: "trzy trzy trzy",
					DetectorGeometry: setup.DetectorPlane{
						Point:  common.Point{X: 1.0, Y: 2.0, Z: 3.0},
						Normal: common.Vec3D{X: -1.0, Y: -2.0, Z: -3.0},
					},
					ScoredParticle: common.HeavyIon{Charge: 10, NucleonsCount: 20},
					ScoringType: setup.LetTypeScoring{
						Type:     "letflu",
						Material: 4,
					},
				},
			},
			MaterialIDToShield: map[setup.MaterialID]material.ShieldID{4: 100},
			Expected: []Detector{
				Detector{
					ScoringType: "PLANE",
					Arguments: []interface{}{
						1.0, 2.0, 3.0, -1.0, -2.0, -3.0,
						"", "", "", int64(25), "LETFLU", "trzy_trzy_trzy0",
						int64(20), int64(10), int64(100), "", "", "",
					},
				},
				Detector{
					ScoringType: "CYL",
					Arguments: []interface{}{
						0.0, -10.0, -20.0, 10.0, 20.0, 30.0,
						int64(10), int64(200), int64(1000), int64(-1), "ENERGY", "dwa_dwa_dwa1",
					},
				},
				Detector{
					ScoringType: "MSH",
					Arguments: []interface{}{
						-5.0, -5.0, 0.0, 5.0, 5.0, 30.0,
						int64(1), int64(1), int64(300), int64(25), "COUNTER", "raz_raz_raz2",
						int64(20), int64(10), "", "", "", "",
					},
				},
			},
			ExpectedSimContext: map[string]setup.DetectorID{
				"trzy_trzy_trzy0": 1,
				"dwa_dwa_dwa1":    2,
				"raz_raz_raz2":    3,
			},
		},
		)
	})
}

func TestCreateDetectorFileName(t *testing.T) {
	for _, tc := range []struct {
		Name     string
		Number   int
		Expected string
	}{
		{"AlaMaKota12321", 4, "alamakota123214"},
		{"yala$234*🧒🏼fdfdf%", 1, "yala_234___fdfdf_1"},
		{"ala123", 1, "ala1231"},
	} {
		assert.Equal(t, tc.Expected, createDetectorFileName(tc.Name, tc.Number))
	}
}
