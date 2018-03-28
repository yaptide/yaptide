package shield

import (
	"github.com/yaptide/converter/setup"
	"github.com/yaptide/converter/shield/detector"
	"github.com/yaptide/converter/shield/geometry"
	"github.com/yaptide/converter/shield/material"
)

// RawShieldSetup is input for shield Serialize function.
type RawShieldSetup struct {
	Materials material.Materials
	Geometry  geometry.Geometry
	Detectors []detector.Detector
	Beam      setup.Beam
	Options   setup.SimulationOptions
}

func (s RawShieldSetup) Files() map[string]string {
	return SerializeData(s)
}
