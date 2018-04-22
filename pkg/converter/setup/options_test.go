package setup

import (
	"testing"

	test "github.com/yaptide/converter/test"
)

var optionTestCasses = test.MarshallingCases{
	{
		&SimulationOptions{
			AntyparticleCorrectionOn:   true,
			NuclearReactionsOn:         true,
			MeanEnergyLoss:             Fraction(0.1),
			MinEnergyLoss:              1.1,
			ScatteringType:             GaussianScattering,
			EnergyStraggling:           VavilovStraggling,
			FastNeutronTransportOn:     true,
			LowEnergyNeutronCutOff:     0.1,
			NumberOfGeneratedParticles: 1000,
		},
		`{
			"antyparticleCorrectionOn": true,
			"nuclearReactionsOn": true,
			"meanEnergyLoss": 0.1,
			"minEnergyLoss": 1.1,
			"scatteringType": "gaussian",
			"energyStraggling": "vavilov",
			"fastNeutronTransportOn": true,
			"lowEnergyNeutronCutOff": 0.1,
			"numberOfGeneratedParticles": 1000
		}`,
	},
}

func TestOptionsMarshal(t *testing.T) {
	test.Marshal(t, optionTestCasses)
}

func TestOptionsUnmarshal(t *testing.T) {
	test.Unmarshal(t, optionTestCasses)
}

func TestOptionsUnmarshalMarshalled(t *testing.T) {
	test.UnmarshalMarshalled(t, optionTestCasses)
}

func TestOptionsMarshalUnmarshalled(t *testing.T) {
	test.MarshalUnmarshalled(t, optionTestCasses)
}
