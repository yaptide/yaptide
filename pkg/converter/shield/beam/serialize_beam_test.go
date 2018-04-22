package beam

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/yaptide/yaptide/pkg/converter/geometry"
	"github.com/yaptide/yaptide/pkg/converter/log"
	"github.com/yaptide/yaptide/pkg/converter/setup"
)

func TestSuccessfullDeafultBeamSerialization(t *testing.T) {
	serialized := Serialize(setup.DefaultBeam, setup.DefaultOptions)
	log.Warning("\n" + serialized)
	log.Warning("\n" + expectedTest1)

	assert.Equal(t, expectedTest1, serialized)
}

const expectedTest1 = `APCORR                 0
BEAMDIR               0.      0.
BEAMPOS               0.      0.      0.
BEAMSIGMA             0.      0.
DELTAE              0.01
DEMIN              0.025
JPART0                 2
MSCAT                  2
NEUTRFAST              1
NEUTRLCUT             0.
NSTAT               1000      -1
NUCRE                  1
STRAGG                 2
TMAX0               100.      0.
`

func TestSuccessfullBeamSerialization(t *testing.T) {
	serialized := Serialize(beamTest2, optionsTest2)
	log.Warning("\n" + serialized)
	log.Warning("\n" + expectedTest2)

	assert.Equal(t, expectedTest2, serialized)
}

var beamTest2 = setup.Beam{
	Direction: setup.BeamDirection{
		Phi: 1, Theta: 1, Position: geometry.Point{X: 110, Y: 1.2220, Z: 0.001},
	},
	Divergence: setup.BeamDivergence{
		SigmaX:       0,
		SigmaY:       0,
		Distribution: setup.GaussianDistribution,
	},
	Particle: setup.Particle{setup.HeavyIon{
		NucleonsCount: 111,
		Charge:        10,
	}},
	InitialBaseEnergy:  100,
	InitialEnergySigma: 1,
}

var optionsTest2 = setup.SimulationOptions{
	AntyparticleCorrectionOn:   true,
	NuclearReactionsOn:         false,
	MeanEnergyLoss:             90,
	MinEnergyLoss:              0.112,
	ScatteringType:             setup.MoliereScattering,
	EnergyStraggling:           setup.VavilovStraggling,
	FastNeutronTransportOn:     false,
	LowEnergyNeutronCutOff:     11.11,
	NumberOfGeneratedParticles: 0,
}

const expectedTest2 = `APCORR                 1
BEAMDIR               1.      1.
BEAMPOS             110.   1.222   0.001
BEAMSIGMA             0.      0.
DELTAE               0.9
DEMIN              0.112
HIPROJ               111      10
JPART0                25
MSCAT                  2
NEUTRFAST              0
NEUTRLCUT          11.11
NSTAT                  0      -1
NUCRE                  0
STRAGG                 2
TMAX0               100.      1.
`
