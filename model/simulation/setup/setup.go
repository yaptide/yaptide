// Package setup implement setup.Setup, which contains simulation setup data.
package setup

import (
	"github.com/Palantir/palantir/model/simulation/setup/beam"
	"github.com/Palantir/palantir/model/simulation/setup/body"
	"github.com/Palantir/palantir/model/simulation/setup/detector"
	"github.com/Palantir/palantir/model/simulation/setup/material"
	"github.com/Palantir/palantir/model/simulation/setup/options"
	"github.com/Palantir/palantir/model/simulation/setup/zone"
)

// MaterialMap type used in Setup structure.
type MaterialMap map[material.ID]*material.Material

// BodyMap type used in Setup structure.
type BodyMap map[body.ID]*body.Body

// ZoneMap type used in Setup structure.
type ZoneMap map[zone.ID]*zone.Zone

// DetectorMap type used in Setup structure.
type DetectorMap map[detector.ID]*detector.Detector

// Setup contains all simulation data.
type Setup struct {
	Materials MaterialMap               `json:"materials"`
	Bodies    BodyMap                   `json:"bodies"`
	Zones     ZoneMap                   `json:"zones"`
	Detectors DetectorMap               `json:"detectors"`
	Beam      beam.Beam                 `json:"beam"`
	Options   options.SimulationOptions `json:"options"`
}

// NewEmptySetup constructor.
func NewEmptySetup() *Setup {
	return &Setup{
		Materials: make(MaterialMap),
		Bodies:    make(BodyMap),
		Zones:     make(ZoneMap),
		Detectors: make(DetectorMap),
		Beam:      beam.Default,
		Options:   options.SimulationOptions{},
	}
}
