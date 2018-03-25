package setup

import (
	"testing"

	test "github.com/yaptide/converter/test"
)

var setupTestCasses = test.MarshallingCases{
	{
		&Setup{
			Materials: MaterialMap{ID(40): nil, ID(34): nil},
			Bodies:    BodyMap{ID(1): nil, ID(2): nil},
			Zones:     ZoneMap{ID(100): nil, ID(200): nil},
			Detectors: DetectorMap{ID(1): nil, ID(2): nil},
			Beam:      DefaultBeam,
			Options:   SimulationOptions{},
		},
		`{
			"materials": {
				"34": null,
				"40": null
			},
			"bodies": {
				"1": null,
				"2": null
			},
			"zones": {
				"100": null,
				"200": null
			},
			"detectors": {
				"1": null,
				"2": null
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
				"particleType": {
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
