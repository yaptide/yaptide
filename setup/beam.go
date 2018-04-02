package setup

import (
	"github.com/yaptide/converter/geometry"
)

// Beam ...
type Beam struct {
	// Direction ...
	// SHIELD doc: BEAMDIR, BEAMPOS
	Direction BeamDirection `json:"direction"`
	// Divergance ...
	// SHIELD doc: BEAMDIV
	Divergence BeamDivergence `json:"divergence"`

	// Particle ...
	// SHIELD doc: HIPROJ, JPART0
	Particle Particle `json:"particle"`

	// InitialBaseEnergy ...
	// SHIELD doc: TMAX0
	InitialBaseEnergy float64 `json:"initialBaseEnergy"`
	// InitialEnergySigma ...
	// SHIELD doc: TMAX0
	InitialEnergySigma float64 `json:"initialEnergySigma"`
}

// Default represents default beam configuration.
var DefaultBeam = Beam{
	Direction: BeamDirection{
		Phi: 0, Theta: 0, Position: geometry.Point{X: 0, Y: 0, Z: 0},
	},
	Divergence: BeamDivergence{
		SigmaX:       0,
		SigmaY:       0,
		Distribution: GaussianDistribution,
	},
	Particle:           Particle{PredefinedParticle("proton")},
	InitialBaseEnergy:  100,
	InitialEnergySigma: 0,
}

// BeamDirection ...
type BeamDirection struct {
	// Phi is angle between positive x axis and direction after cast on xy plane.
	Phi float64 `json:"phi"`
	// Theta is angle between z axis and direction.
	Theta    float64        `json:"theta"`
	Position geometry.Point `json:"position"`
}

// BeamDivergence ...
type BeamDivergence struct {
	SigmaX       float64      `json:"sigmaX"`
	SigmaY       float64      `json:"sigmaY"`
	Distribution Distribution `json:"distribution"`
}
