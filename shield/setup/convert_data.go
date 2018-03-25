package setup

import (
	"fmt"

	"github.com/yaptide/converter"
	"github.com/yaptide/converter/setup"
	"github.com/yaptide/converter/shield/context"
)

// Data is input for shield Serialize function.
type Data struct {
	// Data needed for mat.dat file serialization.
	Materials Materials

	// Data needed for geo.dat file serialization.
	Geometry Geometry

	// Data needed for detect.dat file serialization.
	Detectors []Detector
	// Data needed for setup.dat file serialization.
	Beam setup.Beam

	// Data needed for setup.dat file serialization.
	Options setup.SimulationOptions
}

// Convert simulation setup model to easily serializable data,
// which is input for shield serializer.
// Return error, if setup data are not semantically correct.
func Convert(setup converter.Setup) (RawShieldSetup, context.SerializationContext, error) {
	simContext := context.NewSerializationContext()

	err := checkSetupCompleteness(setup)
	if err != nil {
		return RawShieldSetup{}, simContext, err
	}

	materials, materialIDToShield, err := convertSetupMaterials(
		setup.Materials, &simContext,
	)
	if err != nil {
		return RawShieldSetup{}, simContext, err
	}

	geometry, err := convertSetupGeometry(
		setup.Bodies, setup.Zones, materialIDToShield, &simContext,
	)
	if err != nil {
		return RawShieldSetup{}, simContext, err
	}

	detectors, err := convertSetupDetectors(
		setup.Detectors, materialIDToShield, &simContext,
	)
	if err != nil {
		return RawShieldSetup{}, simContext, err
	}

	return RawShieldSetup{
			Materials: materials,
			Geometry:  geometry,
			Detectors: detectors,
			Beam:      setup.Beam,
			Options:   setup.Options,
		},
		simContext,
		nil
}

func checkSetupCompleteness(setup converter.Setup) error {
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
