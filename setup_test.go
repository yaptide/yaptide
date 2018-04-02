package converter

import (
	"testing"

	"github.com/yaptide/converter/setup"
	test "github.com/yaptide/converter/test"
)

var setupTestCasses = test.MarshallingCases{
	{
		&Setup{
			Materials: MaterialMap{},
			Bodies:    BodyMap{},
			Zones:     ZoneMap{},
			Detectors: DetectorMap{},
			Beam:      setup.DefaultBeam,
			Options:   setup.SimulationOptions{},
		},
		`{
			"materials": {
			},
			"bodies": {
			},
			"zones": {
			},
			"detectors": {
			},
			"beam": {
				"direction": {
					"phi": 0,
					"theta": 0,
					"position": {
						"x": 0,
						"y": 0,
						"z": 0
					}
				},
				"divergence": {
					"sigmaX": 0,
					"sigmaY": 0,
					"distribution": "gaussian"
				},
				"particle": {
					"type": "proton"
				},
				"initialBaseEnergy": 100,
				"initialEnergySigma": 0
			},
			"options": {
				"antyparticleCorrectionOn": false,
				"nuclearReactionsOn": false,
				"meanEnergyLoss": 0,
				"minEnergyLoss": 0,
				"scatteringType": "",
				"energyStraggling": "",
				"fastNeutronTransportOn": false,
				"lowEnergyNeutronCutOff": 0,
				"numberOfGeneratedParticles": 0
			}

		}`,
	},
}

func TestSetupMarshal(t *testing.T) {
	test.Marshal(t, setupTestCasses)
}

func TestSetupUnmarshal(t *testing.T) {
	test.Unmarshal(t, setupTestCasses)
}

func TestSetupUnmarshalMarshalled(t *testing.T) {
	test.UnmarshalMarshalled(t, setupTestCasses)
}

func TestSetupMarshalUnmarshalled(t *testing.T) {
	test.MarshalUnmarshalled(t, setupTestCasses)
}
