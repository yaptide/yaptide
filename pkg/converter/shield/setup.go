package shield

import (
	"github.com/yaptide/yaptide/pkg/converter/setup"
	"github.com/yaptide/yaptide/pkg/converter/shield/detector"
	"github.com/yaptide/yaptide/pkg/converter/shield/geometry"
	"github.com/yaptide/yaptide/pkg/converter/shield/material"
)

// RawShieldSetup is input for shield Serialize function.
type RawShieldSetup struct {
	Materials material.Materials
	Geometry  geometry.Geometry
	Detectors []detector.Detector
	Beam      setup.Beam
	Options   setup.SimulationOptions
}

// Files ...
func (s RawShieldSetup) Files() map[string]string {
	return SerializeData(s)
}
