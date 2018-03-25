// Package setup implement setup.Setup, which contains simulation setup data.
package setup

// MaterialMap type used in Setup structure.
type MaterialMap map[ID]*Material

// BodyMap type used in Setup structure.
type BodyMap map[ID]*Body

// ZoneMap type used in Setup structure.
type ZoneMap map[ID]*Zone

// DetectorMap type used in Setup structure.
type DetectorMap map[ID]*Detector

// Setup contains all simulation data.
type Setup struct {
	Materials MaterialMap       `json:"materials" bson:"materials"`
	Bodies    BodyMap           `json:"bodies" bson:"bodies"`
	Zones     ZoneMap           `json:"zones" bson:"zones"`
	Detectors DetectorMap       `json:"detectors" bson:"detectors"`
	Beam      Beam              `json:"beam" bson:"beam"`
	Options   SimulationOptions `json:"options" bson:"options"`
}

// NewEmptySetup constructor.
func NewEmptySetup() Setup {
	return Setup{
		Materials: make(MaterialMap),
		Bodies:    make(BodyMap),
		Zones:     make(ZoneMap),
		Detectors: make(DetectorMap),
		Beam:      DefaultBeam,
		Options:   DefaultOptions,
	}
}
