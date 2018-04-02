package shield

import (
	"fmt"

	"github.com/yaptide/converter"
	"github.com/yaptide/converter/shield/detector"
	"github.com/yaptide/converter/shield/geometry"
	"github.com/yaptide/converter/shield/material"
)

// Convert simulation setup model to easily serializable data,
// which is input for shield serializer.
// Return error, if setup data are not semantically correct.
func Convert(setup converter.Setup) (RawShieldSetup, SerializationContext, error) {
	simContext := NewSerializationContext()

	err := checkSetupCompleteness(setup)
	if err != nil {
		return RawShieldSetup{}, simContext, err
	}

	materials, materialIDToShield, materialErr := material.ConvertSetupMaterials(setup.Materials)
	geometry, mapBodyToShield, geometryErr := geometry.ConvertSetupGeometry(
		setup.Bodies, setup.Zones, materialIDToShield,
	)
	detectors, mapDetectorToShield, detectorErr := detector.ConvertSetupDetectors(
		setup.Detectors, materialIDToShield,
	)

	for key, value := range materialIDToShield {
		simContext.MapMaterialID[value] = key
	}

	for key, value := range mapBodyToShield {
		simContext.MapBodyID[value] = key
	}

	simContext.MapFilenameToDetectorID = mapDetectorToShield

	_, _, _ = materialErr, geometryErr, detectorErr

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
