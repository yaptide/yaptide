package setup

import (
	"testing"

	"github.com/yaptide/converter/common"
	test "github.com/yaptide/converter/test"
)

var testCases = test.MarshallingCases{
	{
		&Beam{
			Direction: Direction{
				Phi: 0.1, Theta: 0.1, Position: common.Point{X: 1, Y: 1, Z: 1},
			},
			Divergence: Divergence{
				SigmaX:       1,
				SigmaY:       1,
				Distribution: common.GaussianDistribution,
			},
			ParticleType:       common.PredefinedParticle("neutron"),
			InitialBaseEnergy:  111.111,
			InitialEnergySigma: 0.11,
		},
		`{
			"direction": {
				"phi": 0.1,
				"theta": 0.1,
				"position": {
					"x": 1,
					"y": 1,
					"z": 1
				}
			},
			"divergence": {
				"sigmaX": 1,
				"sigmaY": 1,
				"distribution": "gaussian"
			},
			"particleType": {
				"type": "neutron"
			},
			"initialBaseEnergy": 111.111,
			"initialEnergySigma": 0.11
		}`,
	}, {
		&Beam{
			Direction: Direction{
				Phi: 0.1, Theta: 0.1, Position: common.Point{X: 1, Y: 1, Z: 1},
			},
			Divergence: Divergence{
				SigmaX:       1,
				SigmaY:       1,
				Distribution: common.FlatDistribution,
			},
			ParticleType: common.HeavyIon{
				Charge:        10,
				NucleonsCount: 10,
			},
			InitialBaseEnergy:  111.111,
			InitialEnergySigma: 0.11,
		},
		`{
			"direction": {
				"phi": 0.1,
				"theta": 0.1,
				"position": {
					"x": 1,
					"y": 1,
					"z": 1
				}
			},
			"divergence": {
				"sigmaX": 1,
				"sigmaY": 1,
				"distribution": "flat"
			},
			"particleType": {
				"type": "heavy_ion",
				"charge": 10,
				"nucleonsCount": 10
			},
			"initialBaseEnergy": 111.111,
			"initialEnergySigma": 0.11
		}`},
}

func TestBeamMarshal(t *testing.T) {
	test.Marshal(t, testCases)
}

func TestBeamUnmarshal(t *testing.T) {
	test.Unmarshal(t, testCases)
}

func TestBeamUnmarshalMarshalled(t *testing.T) {
	test.UnmarshalMarshalled(t, testCases)
}

func TestBeamMarshalUnmarshalled(t *testing.T) {
	test.MarshalUnmarshalled(t, testCases)
}
