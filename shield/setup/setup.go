// Package setup provide parser and serializer to convert models <-> SHIELD.
package setup

import (
	"github.com/yaptide/converter/setup/beam"
	"github.com/yaptide/converter/setup/options"
)

// RawShieldSetup is input for shield Serialize function.
type RawShieldSetup struct {
	Materials Materials
	Geometry  Geometry
	Detectors []Detector
	Beam      beam.Beam
	Options   options.SimulationOptions
}

func (s RawShieldSetup) Files() map[string]string {
	return SerializeData(s)
}
