package material

import (
	"errors"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/yaptide/converter"
	"github.com/yaptide/converter/setup"
	"github.com/yaptide/converter/shield/mapping"
)

func TestSuccessfullMaterialsConvert(t *testing.T) {
	type testCase struct {
		Input                      converter.MaterialMap
		Expected                   Materials
		ExpectedMaterialIDToShield map[setup.MaterialID]ShieldID
	}

	check := func(t *testing.T, tc testCase) {
		t.Helper()

		actual, actualMaterialIDToShield, actualErr := ConvertSetupMaterials(tc.Input)

		assert.Equal(t, nil, actualErr)
		assert.Equal(t, tc.Expected, actual)
		assert.Equal(t, tc.ExpectedMaterialIDToShield, actualMaterialIDToShield)
	}

	convertedSimplePredefined := PredefinedMaterial{
		ICRUNumber:    mapping.MaterialICRU(273),
		StateOfMatter: mapping.StateNonDefined,
	}

	convertedFullPredefined := PredefinedMaterial{
		ICRUNumber:                mapping.MaterialICRU(198),
		StateOfMatter:             mapping.StateLiquid,
		Density:                   123.45,
		LoadExternalStoppingPower: true,
	}

	convertedCompound := CompoundMaterial{
		StateOfMatter: mapping.StateSolid,
		Density:       99.9,
		ExternalStoppingPowerFromMaterialICRU: 277,
		Elements: []Element{
			Element{
				ID: 64,
				RelativeStoichiometricFraction: 2,
				AtomicMass:                     100.23,
				IValue:                         0.0,
			},
			Element{
				ID: 103,
				RelativeStoichiometricFraction: 123,
				AtomicMass:                     0.0,
				IValue:                         555.34,
			},
		},
		serializeExternalStoppingPower: true,
	}

	convertedAnotherCompound := CompoundMaterial{
		StateOfMatter: mapping.StateGas,
		Density:       0.999,
		ExternalStoppingPowerFromMaterialICRU: 277,
		Elements: []Element{
			Element{
				ID: 6,
				RelativeStoichiometricFraction: 4,
				AtomicMass:                     0.01,
				IValue:                         0.0,
			},
			Element{
				ID: 14,
				RelativeStoichiometricFraction: 1,
				AtomicMass:                     0.0,
				IValue:                         0.34,
			},
			Element{
				ID: 11,
				RelativeStoichiometricFraction: 11111,
				AtomicMass:                     987.654,
				IValue:                         0.123,
			},
		},
		serializeExternalStoppingPower: true,
	}

	t.Run("OnePredefined", func(t *testing.T) {
		check(t,
			testCase{
				Input: createMaterialMap(genSetupSimplePredefined(1)),
				Expected: Materials{
					Predefined: []PredefinedMaterial{setPredefinedID(convertedSimplePredefined, 1)},
					Compound:   []CompoundMaterial{},
				},
				ExpectedMaterialIDToShield: map[setup.MaterialID]ShieldID{1: 1},
			})

		check(t,
			testCase{
				Input: createMaterialMap(genSetupFullPredefined(6)),
				Expected: Materials{
					Predefined: []PredefinedMaterial{setPredefinedID(convertedFullPredefined, 1)},
					Compound:   []CompoundMaterial{},
				},
				ExpectedMaterialIDToShield: map[setup.MaterialID]ShieldID{6: 1},
			},
		)
	})

	t.Run("OneCompound", func(t *testing.T) {
		check(t,
			testCase{
				Input: createMaterialMap(genSetupCompound(1001)),
				Expected: Materials{
					Predefined: []PredefinedMaterial{},
					Compound:   []CompoundMaterial{setCompoundID(convertedCompound, 1)},
				},
				ExpectedMaterialIDToShield: map[setup.MaterialID]ShieldID{1001: 1},
			})

		check(t,
			testCase{
				Input: createMaterialMap(genSetupAnotherCompound(4000)),
				Expected: Materials{
					Predefined: []PredefinedMaterial{},
					Compound:   []CompoundMaterial{setCompoundID(convertedAnotherCompound, 1)},
				},
				ExpectedMaterialIDToShield: map[setup.MaterialID]ShieldID{4000: 1},
			})
	})

	t.Run("FewPredefined", func(t *testing.T) {
		check(t,
			testCase{
				Input: createMaterialMap(
					genSetupSimplePredefined(1),
					genSetupFullPredefined(2)),
				Expected: Materials{
					Predefined: []PredefinedMaterial{
						setPredefinedID(convertedSimplePredefined, 1),
						setPredefinedID(convertedFullPredefined, 2),
					},
					Compound: []CompoundMaterial{},
				},
				ExpectedMaterialIDToShield: map[setup.MaterialID]ShieldID{1: 1, 2: 2},
			})

		check(t,
			testCase{
				Input: createMaterialMap(
					genSetupSimplePredefined(2),
					genSetupFullPredefined(1)),
				Expected: Materials{
					Predefined: []PredefinedMaterial{
						setPredefinedID(convertedFullPredefined, 1),
						setPredefinedID(convertedSimplePredefined, 2),
					},
					Compound: []CompoundMaterial{},
				},
				ExpectedMaterialIDToShield: map[setup.MaterialID]ShieldID{1: 1, 2: 2},
			})
	})

	t.Run("FewCompound", func(t *testing.T) {
		check(t,
			testCase{
				Input: createMaterialMap(
					genSetupCompound(1),
					genSetupAnotherCompound(2)),
				Expected: Materials{
					Predefined: []PredefinedMaterial{},
					Compound: []CompoundMaterial{
						setCompoundID(convertedCompound, 1),
						setCompoundID(convertedAnotherCompound, 2),
					},
				},
				ExpectedMaterialIDToShield: map[setup.MaterialID]ShieldID{1: 1, 2: 2},
			})
		check(t,
			testCase{
				Input: createMaterialMap(
					genSetupCompound(2),
					genSetupAnotherCompound(1)),
				Expected: Materials{
					Predefined: []PredefinedMaterial{},
					Compound: []CompoundMaterial{
						setCompoundID(convertedAnotherCompound, 1),
						setCompoundID(convertedCompound, 2),
					},
				},
				ExpectedMaterialIDToShield: map[setup.MaterialID]ShieldID{1: 1, 2: 2},
			})

	})

	t.Run("Mixed", func(t *testing.T) {
		check(t,
			testCase{
				Input: createMaterialMap(
					genSetupSimplePredefined(1),
					genSetupFullPredefined(2),
					genSetupCompound(3),
					genSetupAnotherCompound(4)),
				Expected: Materials{
					Predefined: []PredefinedMaterial{
						setPredefinedID(convertedSimplePredefined, 1),
						setPredefinedID(convertedFullPredefined, 2),
					},
					Compound: []CompoundMaterial{
						setCompoundID(convertedCompound, 3),
						setCompoundID(convertedAnotherCompound, 4),
					},
				},
				ExpectedMaterialIDToShield: map[setup.MaterialID]ShieldID{1: 1, 2: 2, 3: 3, 4: 4},
			})

		check(t,
			testCase{
				Input: createMaterialMap(
					genSetupSimplePredefined(9),
					genSetupFullPredefined(2),
					genSetupCompound(100),
					genSetupAnotherCompound(3),
					genSetupSimplePredefined(1),
				),
				Expected: Materials{
					Predefined: []PredefinedMaterial{
						setPredefinedID(convertedSimplePredefined, 1),
						setPredefinedID(convertedFullPredefined, 2),
						setPredefinedID(convertedSimplePredefined, 3),
					},
					Compound: []CompoundMaterial{
						setCompoundID(convertedAnotherCompound, 4),
						setCompoundID(convertedCompound, 5),
					},
				},
				ExpectedMaterialIDToShield: map[setup.MaterialID]ShieldID{1: 1, 2: 2, 9: 3, 3: 4, 100: 5},
			})
	})

	t.Run("VacuumShouldBeNotSerialized", func(t *testing.T) {
		check(t,
			testCase{
				Input: createMaterialMap(genVacuum(1)),
				Expected: Materials{
					Predefined: []PredefinedMaterial{},
					Compound:   []CompoundMaterial{},
				},
				ExpectedMaterialIDToShield: map[setup.MaterialID]ShieldID{1: 1000},
			})

		check(t,
			testCase{
				Input: createMaterialMap(
					genSetupSimplePredefined(1),
					genVacuum(2),
					genSetupAnotherCompound(3)),
				Expected: Materials{
					Predefined: []PredefinedMaterial{
						setPredefinedID(convertedSimplePredefined, 1),
					},
					Compound: []CompoundMaterial{
						setCompoundID(convertedAnotherCompound, 2),
					},
				},
				ExpectedMaterialIDToShield: map[setup.MaterialID]ShieldID{1: 1, 2: 1000, 3: 2},
			})

	})

}

func TestBadInputMaterialsConvert(t *testing.T) {
	type testCase struct {
		Input         converter.MaterialMap
		ExpectedError error
	}

	check := func(t *testing.T, tc testCase) {
		t.Helper()

		actual, _, actualErr := ConvertSetupMaterials(tc.Input)

		assert.Equal(t, Materials{}, actual)
		assert.Equal(t, tc.ExpectedError, actualErr)
	}

	t.Run("ToManyMaterials", func(t *testing.T) {
		const materialsN = 1000
		materials := converter.MaterialMap{}
		for i := int64(0); i < materialsN; i++ {
			materials[setup.MaterialID(i)] = genSetupSimplePredefined(i)
		}

		check(t, testCase{
			Input: materials,
			ExpectedError: errors.New(
				"[serializer] mat.dat: Only 100 distinct materials" +
					" are permitted in shield (1000 > 100)",
			),
		})
	})

	t.Run("VoxelNotImplemented", func(t *testing.T) {
		const materialsN = 1000
		materials := converter.MaterialMap{}
		for i := int64(0); i < materialsN; i++ {
			materials[setup.MaterialID(i)] = genSetupSimplePredefined(i)
		}

		check(t, testCase{
			Input: createMaterialMap(
				setup.Material{
					ID:    1,
					Specs: setup.MaterialSpecs{setup.MaterialVoxel{}},
				},
			),
			ExpectedError: errors.New(
				"[serializer] Material{Id: 1} -> mat.dat: Voxel material" +
					" serialization not implemented",
			),
		})
	})

	t.Run("PredefinedMappingNotFound", func(t *testing.T) {
		const id = 1
		mat := genSetupSimplePredefined(id)
		predef := mat.Specs.MaterialType.(setup.MaterialPredefined)
		predef.PredefinedID = "predefNameNotDefined"
		mat.Specs.MaterialType = predef

		check(t, testCase{
			Input: createMaterialMap(mat),
			ExpectedError: errors.New(
				"[serializer] Material{Id: 1} -> mat.dat: \"predefNameNotDefined\"" +
					" material mapping to shield format not found",
			),
		})
	})

	t.Run("IsotopeMappingNotFound", func(t *testing.T) {
		const id = 1
		mat := genSetupCompound(id)
		compound := mat.Specs.MaterialType.(setup.MaterialCompound)
		compound.Elements[0].Isotope = "isotopeNameNotDefined"
		mat.Specs.MaterialType = compound

		check(t, testCase{
			Input: createMaterialMap(mat),
			ExpectedError: errors.New(
				"[serializer] Material{Id: 1} -> mat.dat: \"isotopeNameNotDefined\"" +
					" isotope mapping to shield format not found",
			),
		})
	})

	t.Run("ExternalStoppingPowerFromPredefinedMaterialMappingNotFound", func(t *testing.T) {
		const id = 1
		mat := genSetupCompound(id)
		compound := mat.Specs.MaterialType.(setup.MaterialCompound)
		compound.ExternalStoppingPowerFromPredefined = "espfpNameNotDefined"
		mat.Specs.MaterialType = compound
		check(t, testCase{
			Input: createMaterialMap(mat),
			ExpectedError: errors.New(
				"[serializer] Material{Id: 1} -> mat.dat: \"espfpNameNotDefined\"" +
					" material mapping to shield format not found",
			),
		})
	})

}

func genSetupSimplePredefined(id int64) setup.Material {
	return setup.Material{
		ID: setup.MaterialID(id),
		Specs: setup.MaterialSpecs{setup.MaterialPredefined{
			PredefinedID: "urea",
		}},
	}
}

func genSetupFullPredefined(id int64) setup.Material {
	return setup.Material{
		ID: setup.MaterialID(id),
		Specs: setup.MaterialSpecs{setup.MaterialPredefined{
			PredefinedID:              "methanol",
			StateOfMatter:             setup.Liquid,
			Density:                   123.45,
			LoadExternalStoppingPower: true,
		}},
	}
}

func genSetupCompound(id int64) setup.Material {
	return setup.Material{
		ID: setup.MaterialID(id),
		Specs: setup.MaterialSpecs{setup.MaterialCompound{
			Name:          "kot",
			Density:       99.9,
			StateOfMatter: setup.Solid,
			Elements: []setup.Element{
				setup.Element{Isotope: "gd-*", RelativeStoichiometricFraction: 2, AtomicMass: 100.23},
				setup.Element{Isotope: "u-235", RelativeStoichiometricFraction: 123, IValue: 555.34},
			},
			ExternalStoppingPowerFromPredefined: "water_vapor",
		}},
	}
}

func genSetupAnotherCompound(id int64) setup.Material {
	return setup.Material{
		ID: setup.MaterialID(id),
		Specs: setup.MaterialSpecs{setup.MaterialCompound{
			Name:          "pies",
			Density:       0.999,
			StateOfMatter: setup.Gas,
			Elements: []setup.Element{
				setup.Element{Isotope: "c-*", RelativeStoichiometricFraction: 4, AtomicMass: 0.01},
				setup.Element{Isotope: "si-*", RelativeStoichiometricFraction: 1, IValue: 0.34},
				setup.Element{
					Isotope: "na-23",
					RelativeStoichiometricFraction: 11111,
					IValue:     0.123,
					AtomicMass: 987.654,
				},
			},
			ExternalStoppingPowerFromPredefined: "water_vapor",
		}},
	}
}

func genVacuum(id int64) setup.Material {
	return setup.Material{
		ID: setup.MaterialID(id),
		Specs: setup.MaterialSpecs{setup.MaterialPredefined{
			PredefinedID: "vacuum",
		}},
	}
}

func createMaterialMap(materials ...setup.Material) converter.MaterialMap {
	res := converter.MaterialMap{}
	for _, m := range materials {
		res[m.ID] = m
	}
	return res
}

func setPredefinedID(mat PredefinedMaterial, id ShieldID) PredefinedMaterial {
	mat.ID = id
	return mat
}

func setCompoundID(mat CompoundMaterial, id ShieldID) CompoundMaterial {
	mat.ID = id
	return mat
}
