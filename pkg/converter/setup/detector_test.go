package setup

import (
	"testing"

	"github.com/yaptide/yaptide/pkg/converter/geometry"
	test "github.com/yaptide/yaptide/pkg/converter/test"
)

var detectorTestCasses = test.MarshallingCases{
	{
		&Detector{
			ID:   DetectorID(1),
			Name: "ala",
			DetectorGeometry: DetectorGeometry{DetectorMesh{
				Center: geometry.Point{X: 1, Y: 2, Z: 3},
				Size:   geometry.Vec3D{X: 1, Y: 2, Z: 3},
				Slices: geometry.Vec3DInt{X: 10, Y: 10, Z: 10},
			}},
			ScoredParticle: Particle{AllParticles("all")},
			Scoring:        DetectorScoring{PredefinedScoring("energy")},
		},
		`{
			"id": 1,
			"name": "ala",
			"detectorGeometry": {
				"type": "mesh",
				"center": {
					"x": 1,
					"y": 2,
					"z": 3
				},
				"size": {
					"x": 1,
					"y": 2,
					"z": 3
				},
				"slices": {
					"x": 10,
					"y": 10,
					"z": 10
				}
			},
			"particle": {
				"type": "all"
			},
			"scoring": {
				"type": "energy"
			}
		}`,
	}, {
		&Detector{
			ID:   DetectorID(1),
			Name: "ma",
			DetectorGeometry: DetectorGeometry{DetectorMesh{
				Center: geometry.Point{X: 1, Y: 2, Z: 3},
				Size:   geometry.Vec3D{X: 1, Y: 2, Z: 3},
				Slices: geometry.Vec3DInt{X: 10, Y: 10, Z: 10},
			}},
			ScoredParticle: Particle{HeavyIon{Charge: 10, NucleonsCount: 10}},
			Scoring:        DetectorScoring{LetTypeScoring{Type: "tlet", Material: 0}},
		},
		`{
			"id": 1,
			"name": "ma",
			"detectorGeometry": {
				"type": "mesh",
				"center": {
					"x": 1,
					"y": 2,
					"z": 3
				},
				"size": {
					"x": 1,
					"y": 2,
					"z": 3
				},
				"slices": {
					"x": 10,
					"y": 10,
					"z": 10
				}
			},
			"particle": {
				"type": "heavy_ion",
				"charge": 10,
				"nucleonsCount": 10
			},
			"scoring": {
				"type": "tlet",
				"material": 0
			}
		}`,
	},
}

func TestDetectorMarshal(t *testing.T) {
	test.Marshal(t, detectorTestCasses)
}

func TestDetectorUnmarshal(t *testing.T) {
	test.Unmarshal(t, detectorTestCasses)
}

func TestDetectorUnmarshalMarshalled(t *testing.T) {
	test.UnmarshalMarshalled(t, detectorTestCasses)
}

func TestDetectorMarshalUnmarshalled(t *testing.T) {
	test.MarshalUnmarshalled(t, detectorTestCasses)
}
