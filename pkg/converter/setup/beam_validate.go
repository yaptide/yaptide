package setup

import (
	"fmt"

	"github.com/yaptide/yaptide/pkg/converter/validate"
)

// Validate ...
func (b Beam) Validate() error {
	result := E{}

	if err := b.Direction.Validate(); err != nil {
		result["direction"] = err
	}
	if err := b.Divergence.Validate(); err != nil {
		result["divergence"] = err
	}
	//if err := b.ParticleType.Validate(); err != nil {
	//		result["particleType"] = err
	//	}

	if b.InitialBaseEnergy < 0 {
		result["initialBaseEnergy"] = fmt.Errorf("shuld be positive value")
	}

	if b.InitialEnergySigma < 0 {
		result["initialEnergySigma"] = fmt.Errorf("should be positive value")
	}

	return result
}

// Validate ...
func (b BeamDirection) Validate() error {
	result := E{}

	if !validate.InRange2PI(b.Phi) {
		result["phi"] = fmt.Errorf("should be between 0 and 2PI")
	}
	if !validate.InRangePI(b.Theta) {
		result["theta"] = fmt.Errorf("should be between 0 and PI")
	}

	return result
}

// Validate ...
func (b BeamDivergence) Validate() error {
	result := E{}
	// TODO research this better;
	return result
}
