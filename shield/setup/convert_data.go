package setup

import (
	"fmt"

	"github.com/yaptide/converter/setup"
	"github.com/yaptide/converter/setup/beam"
	"github.com/yaptide/converter/setup/options"
	"github.com/yaptide/converter/shield"
)

// Data is input for shield Serialize function.
type Data struct {
	// Data needed for mat.dat file serialization.
	Materials Materials

	// Data needed for geo.dat file serialization.
	Geometry Geometry

	// Data needed for detect.dat file serialization.
	Detectors []Detector
	// Data needed for beam.dat file serialization.
	Beam beam.Beam

	// Data needed for beam.dat file serialization.
	Options options.SimulationOptions
}

// Convert simulation setup model to easily serializable data,
// which is input for shield serializer.
// Return error, if setup data are not semantically correct.
func Convert(setup setup.Setup) (*RawShieldSetup, *shield.SerializationContext, error) {
	err := checkSetupCompleteness(setup)
	if err != nil {
		return nil, nil, err
	}

	simContext := shield.NewSerializationContext()

	materials, materialIDToShield, err := convertSetupMaterials(setup.Materials, simContext)
	if err != nil {
		return nil, nil, err
	}

	geometry, err := convertSetupGeometry(setup.Bodies, setup.Zones, materialIDToShield, simContext)
	if err != nil {
		return nil, nil, err
	}

	detectors, err := convertSetupDetectors(setup.Detectors, materialIDToShield, simContext)
	if err != nil {
		return nil, nil, err
	}

	return &RawShieldSetup{
			Materials: materials,
			Geometry:  geometry,
			Detectors: detectors,
			Beam:      setup.Beam,
			Options:   setup.Options,
		},
		simContext,
		nil
}

func checkSetupCompleteness(setup setup.Setup) error {
	createMissingError := func(mapName string) error {
		return fmt.Errorf("[serializer]: %s map is null", mapName)
	}

	createEmptyError := func(mapName string) error {
		return fmt.Errorf("[serializer]: %s map is empty", mapName)
	}

	switch {
	case setup.Bodies == nil:
		return createMissingError("Bodies")
	case setup.Zones == nil:
		return createMissingError("Zones")
	case setup.Materials == nil:
		return createMissingError("Materials")
	case setup.Detectors == nil:
		return createMissingError("Detectors")
	}

	switch {
	case len(setup.Bodies) == 0:
		return createEmptyError("Bodies")
	case len(setup.Zones) == 0:
		return createEmptyError("Zones")
	case len(setup.Materials) == 0:
		return createEmptyError("Materials")
	case len(setup.Detectors) == 0:
		return createEmptyError("Detectors")
	}

	return nil
}
