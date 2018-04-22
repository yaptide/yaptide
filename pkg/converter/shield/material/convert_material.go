package material

import (
	"sort"

	"github.com/yaptide/converter"
	"github.com/yaptide/converter/setup"
	"github.com/yaptide/converter/shield/mapping"
)

// ShieldID ...
type ShieldID int

// Materials contains representation of setup.MaterialsMap,
// which is easily serializable in shield serializer.
type Materials struct {
	Predefined []PredefinedMaterial
	Compound   []CompoundMaterial
}

// PredefinedMaterial represent setup.Predefined.
type PredefinedMaterial struct {
	ID                        ShieldID
	ICRUNumber                mapping.MaterialICRU
	StateOfMatter             mapping.StateOfMatter
	Density                   float64
	LoadExternalStoppingPower bool
}

// Element represent setup.Element.
type Element struct {
	ID                             mapping.IsotopeNUCLID
	RelativeStoichiometricFraction int64
	AtomicMass                     float64
	IValue                         float64
}

// CompoundMaterial represent setup.Compound.
type CompoundMaterial struct {
	ID                                    ShieldID
	StateOfMatter                         mapping.StateOfMatter
	Density                               float64
	ExternalStoppingPowerFromMaterialICRU mapping.MaterialICRU
	Elements                              []Element

	serializeExternalStoppingPower bool
}

// ConvertSetupMaterials ...
func ConvertSetupMaterials(
	setupMat converter.MaterialMap,
) (Materials, map[setup.MaterialID]ShieldID, error) {
	result := Materials{
		Predefined: []PredefinedMaterial{},
		Compound:   []CompoundMaterial{},
	}

	materialIDToShield := map[setup.MaterialID]ShieldID{}

	const maxMaterialsNumber = 100

	if len(setupMat) > maxMaterialsNumber {
		return Materials{}, nil, converter.GeneralMatError(
			"Only %d distinct materials are permitted in shield (%d > %d)",
			maxMaterialsNumber,
			len(setupMat),
			maxMaterialsNumber,
		)
	}

	predefMaterialsIds := []setup.MaterialID{}
	compoundMaterialsIds := []setup.MaterialID{}

	for id, mat := range setupMat {
		switch g := mat.Specs.MaterialType.(type) {
		case setup.MaterialPredefined:
			if g.PredefinedID != "vacuum" {
				predefMaterialsIds = append(predefMaterialsIds, id)
			} else {
				materialIDToShield[id] = ShieldID(mapping.PredefinedMaterialsToShieldICRU["vacuum"])
			}
		case setup.MaterialCompound:
			compoundMaterialsIds = append(compoundMaterialsIds, id)
		case setup.MaterialVoxel:
			return Materials{}, nil, converter.MaterialIDError(
				mat.ID, "Voxel material serialization not implemented",
			)
		default:
			return Materials{}, nil, converter.MaterialIDError(
				mat.ID, "Unknown material type",
			)
		}
	}

	nextShieldID := 1
	for _, ids := range [][]setup.MaterialID{predefMaterialsIds, compoundMaterialsIds} {
		sort.SliceStable(ids, func(i, j int) bool { return ids[i] < ids[j] })
		for _, id := range ids {
			materialIDToShield[id] = ShieldID(nextShieldID)
			nextShieldID++
		}
	}

	for _, predefID := range predefMaterialsIds {
		predef, err := createPredefinedMaterial(
			setupMat[predefID].Specs.MaterialType.(setup.MaterialPredefined), materialIDToShield[predefID],
		)
		if err != nil {
			return Materials{}, nil, err
		}
		result.Predefined = append(result.Predefined, predef)
	}

	for _, compoundID := range compoundMaterialsIds {
		compound, err := createCompoundMaterial(
			setupMat[compoundID].Specs.MaterialType.(setup.MaterialCompound), materialIDToShield[compoundID],
		)
		if err != nil {
			return Materials{}, nil, err
		}
		result.Compound = append(result.Compound, compound)
	}
	return result, materialIDToShield, nil
}

// SerializeStateOfMatter return true, if StateOfMatter should be serialized.
func (p *PredefinedMaterial) SerializeStateOfMatter() bool {
	return p.StateOfMatter != mapping.StateOfMatterToShield[setup.NonDefined]
}

// SerializeDensity return true, if Density should be serialized.
func (p *PredefinedMaterial) SerializeDensity() bool {
	return p.Density > 0.0
}

// SerializeExternalStoppingPower eturn true, if ExternalStoppingPowerFromMaterialICRU should be
// serialized.
func (c *CompoundMaterial) SerializeExternalStoppingPower() bool {
	return c.serializeExternalStoppingPower
}

// SerializeAtomicMass return true, if AtomicMass should be serialized.
func (e *Element) SerializeAtomicMass() bool {
	return e.AtomicMass > 0.0
}

// SerializeIValue return true, if IValue should be serialized.
func (e *Element) SerializeIValue() bool {
	return e.IValue > 0.0
}

func createPredefinedMaterial(
	predef setup.MaterialPredefined, id ShieldID,
) (PredefinedMaterial, error) {
	ICRUNumber, found := mapping.PredefinedMaterialsToShieldICRU[predef.PredefinedID]
	if !found {
		return PredefinedMaterial{}, converter.MaterialIDError(
			id, "\"%s\" material mapping to shield format not found", predef.PredefinedID,
		)
	}

	return PredefinedMaterial{
		ID:                        id,
		StateOfMatter:             mapping.StateOfMatterToShield[predef.StateOfMatter],
		Density:                   predef.Density,
		ICRUNumber:                ICRUNumber,
		LoadExternalStoppingPower: predef.LoadExternalStoppingPower}, nil
}

func createCompoundMaterial(
	compound setup.MaterialCompound, id ShieldID,
) (CompoundMaterial, error) {
	const maxElementsNumber = 13

	if compound.StateOfMatter == setup.NonDefined {
		return CompoundMaterial{}, converter.MaterialIDError(
			id, "StateOfMatter must be defined for Compound material",
		)
	}
	if compound.Density <= 0.0 {
		return CompoundMaterial{}, converter.MaterialIDError(
			id, "Density must be specified for Compund material",
		)
	}
	if len(compound.Elements) > maxElementsNumber {
		return CompoundMaterial{}, converter.MaterialIDError(
			id, "Only %d elements for Compound are permitted in shield (%d > %d)",
			maxElementsNumber, len(compound.Elements), maxElementsNumber,
		)
	}

	var externalStoppingPowerFromMaterialICRU mapping.MaterialICRU
	var serializeExternalStoppingPower bool

	if compound.ExternalStoppingPowerFromPredefined != "" {
		materialICRU, found := mapping.
			PredefinedMaterialsToShieldICRU[compound.ExternalStoppingPowerFromPredefined]
		if !found {
			return CompoundMaterial{}, converter.MaterialIDError(
				id, "\"%s\" material mapping to shield format not found",
				compound.ExternalStoppingPowerFromPredefined,
			)
		}
		externalStoppingPowerFromMaterialICRU = materialICRU
		serializeExternalStoppingPower = true
	} else {
		serializeExternalStoppingPower = false
	}

	elements := []Element{}
	for _, element := range compound.Elements {
		isotopeNUCLID, found := mapping.IsotopesToShieldNUCLID[element.Isotope]
		if !found {
			return CompoundMaterial{}, converter.MaterialIDError(
				id, "\"%s\" isotope mapping to shield format not found", element.Isotope,
			)
		}
		elements = append(elements, Element{
			ID: isotopeNUCLID,
			RelativeStoichiometricFraction: element.RelativeStoichiometricFraction,
			AtomicMass:                     element.AtomicMass,
			IValue:                         element.IValue,
		})
	}

	return CompoundMaterial{
		ID:            id,
		StateOfMatter: mapping.StateOfMatterToShield[compound.StateOfMatter],
		Density:       compound.Density,
		ExternalStoppingPowerFromMaterialICRU: externalStoppingPowerFromMaterialICRU,
		Elements:                       elements,
		serializeExternalStoppingPower: serializeExternalStoppingPower,
	}, nil
}
