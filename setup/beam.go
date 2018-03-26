package setup

import (
	"encoding/json"

	"github.com/yaptide/converter/common"
)

// Beam ...
type Beam struct {
	// Direction ...
	// SHIELD doc: BEAMDIR, BEAMPOS
	Direction BeamDirection `json:"direction"`
	// Divergance ...
	// SHIELD doc: BEAMDIV
	Divergence BeamDivergence `json:"divergence"`

	// ParticleType ...
	// SHIELD doc: HIPROJ, JPART0
	ParticleType common.Particle `json:"particleType"`

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
		Phi: 0, Theta: 0, Position: common.Point{X: 0, Y: 0, Z: 0},
	},
	Divergence: BeamDivergence{
		SigmaX:       0,
		SigmaY:       0,
		Distribution: common.GaussianDistribution,
	},
	ParticleType:       common.PredefinedParticle("proton"),
	InitialBaseEnergy:  100,
	InitialEnergySigma: 0,
}

// UnmarshalJSON custom Unmarshal function.
func (d *Beam) UnmarshalJSON(b []byte) error {
	type rawBeam struct {
		Direction          BeamDirection   `json:"direction"`
		Divergence         BeamDivergence  `json:"divergence"`
		ParticleType       json.RawMessage `json:"particleType"`
		InitialBaseEnergy  float64         `json:"initialBaseEnergy"`
		InitialEnergySigma float64         `json:"initialEnergySigma"`
	}
	var raw rawBeam
	err := json.Unmarshal(b, &raw)
	if err != nil {
		return nil
	}
	d.Direction = raw.Direction
	d.Divergence = raw.Divergence
	particleType, err := common.UnmarshalParticle(raw.ParticleType)
	if err != nil {
		return err
	}
	d.ParticleType = particleType
	d.InitialBaseEnergy = raw.InitialBaseEnergy
	d.InitialEnergySigma = raw.InitialEnergySigma
	return nil
}

// BeamDirection ...
type BeamDirection struct {
	// Phi is angle between positive x axis and direction after cast on xy plane.
	Phi float64 `json:"phi"`
	// Theta is angle between z axis and direction.
	Theta    float64      `json:"theta"`
	Position common.Point `json:"position"`
}

// BeamDivergence ...
type BeamDivergence struct {
	SigmaX       float64             `json:"sigmaX"`
	SigmaY       float64             `json:"sigmaY"`
	Distribution common.Distribution `json:"distribution"`
}
