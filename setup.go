package converter

import "github.com/yaptide/converter/setup"

// MaterialMap type used in Setup structure.
type MaterialMap map[setup.ID]setup.Material

// BodyMap type used in Setup structure.
type BodyMap map[setup.ID]setup.Body

// ZoneMap type used in Setup structure.
type ZoneMap map[setup.ID]setup.Zone

// DetectorMap type used in Setup structure.
type DetectorMap map[setup.ID]setup.Detector

// Setup contains all simulation data.
type Setup struct {
	Materials MaterialMap             `json:"materials" bson:"materials"`
	Bodies    BodyMap                 `json:"bodies" bson:"bodies"`
	Zones     ZoneMap                 `json:"zones" bson:"zones"`
	Detectors DetectorMap             `json:"detectors" bson:"detectors"`
	Beam      setup.Beam              `json:"beam" bson:"beam"`
	Options   setup.SimulationOptions `json:"options" bson:"options"`
}

// NewEmptySetup constructor.
func NewEmptySetup() Setup {
	return Setup{
		Materials: make(MaterialMap),
		Bodies:    make(BodyMap),
		Zones:     make(ZoneMap),
		Detectors: make(DetectorMap),
		Beam:      setup.DefaultBeam,
		Options:   setup.DefaultOptions,
	}
}
