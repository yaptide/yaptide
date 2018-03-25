// Package setup provide parser and serializer to convert models <-> SHIELD.
package setup

import "github.com/yaptide/converter/setup"

// RawShieldSetup is input for shield Serialize function.
type RawShieldSetup struct {
	Materials Materials
	Geometry  Geometry
	Detectors []Detector
	Beam      setup.Beam
	Options   setup.SimulationOptions
}

func (s RawShieldSetup) Files() map[string]string {
	return SerializeData(s)
}
