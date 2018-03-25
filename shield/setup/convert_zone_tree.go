package setup

import (
	"fmt"

	"github.com/yaptide/converter"
	"github.com/yaptide/converter/setup"
	"github.com/yaptide/converter/shield/context"
)

type operation struct {
	BodyID context.BodyID
	Type   setup.OperationType
}

type zoneTree struct {
	childrens []*zoneTree

	baseBodyID context.BodyID
	operations []operation

	materialID context.MaterialID
}

func convertSetupZonesToZoneTreeForest(
	zoneMap converter.ZoneMap,
	materialIDToShield map[setup.ID]context.MaterialID,
	bodyIDToShield map[setup.ID]context.BodyID) ([]*zoneTree, error) {

	converter := zoneConverter{
		zoneMap:            zoneMap,
		materialIDToShield: materialIDToShield,
		bodyIDToShield:     bodyIDToShield,
	}
	return converter.convertSetupZonesToZoneTreeForest()
}

type zoneConverter struct {
	zoneMap            converter.ZoneMap
	materialIDToShield map[setup.ID]context.MaterialID
	bodyIDToShield     map[setup.ID]context.BodyID
}

func (z *zoneConverter) convertSetupZonesToZoneTreeForest() ([]*zoneTree, error) {
	forest := []*zoneTree{}

	for _, zoneModel := range z.zoneMap {
		if zoneModel.ParentID == setup.RootID {
			newZoneTree, err := z.createZoneTree(&zoneModel)
			if err != nil {
				return nil, err
			}
			forest = append(forest, newZoneTree)
		}
	}
	return forest, nil
}

func (z *zoneConverter) createZoneTree(zoneModel *setup.Zone) (*zoneTree, error) {
	baseBodyID, found := z.bodyIDToShield[zoneModel.BaseID]
	if !found {
		return nil, newZoneIDError(zoneModel.ID, "Cannot find body: %d", zoneModel.BaseID)
	}

	operations, err := z.convertSetupOperations(zoneModel.Construction)
	if err != nil {
		return nil, newZoneIDError(zoneModel.ID, "%s", err.Error)
	}

	materialID, found := z.materialIDToShield[zoneModel.MaterialID]
	if !found {
		return nil, newZoneIDError(zoneModel.ID, "Cannot find material: %d", zoneModel.MaterialID)
	}

	childModelIDs := []setup.ID{}
	for _, zone := range z.zoneMap {
		if zone.ParentID == zoneModel.ID {
			childModelIDs = append(childModelIDs, zone.ID)
		}
	}

	childrens := []*zoneTree{}
	for _, childModelID := range childModelIDs {
		childModel, found := z.zoneMap[childModelID]
		if !found {
			return nil, newZoneIDError(zoneModel.ID, "Can not find Children {ID: %d}", childModelID)
		}

		child, err := z.createZoneTree(&childModel)
		if err != nil {
			return nil, err
		}

		childrens = append(childrens, child)
	}

	return &zoneTree{
		childrens:  childrens,
		baseBodyID: baseBodyID,
		operations: operations,
		materialID: materialID,
	}, nil
}

func (z *zoneConverter) convertSetupOperations(setupOperations []*setup.Operation) ([]operation, error) {
	operations := []operation{}
	for _, o := range setupOperations {
		bodyID, found := z.bodyIDToShield[o.BodyID]
		if !found {
			return nil, fmt.Errorf("Cannot find body: %d", o.BodyID)
		}
		operations = append(operations, operation{
			BodyID: bodyID,
			Type:   o.Type,
		})
	}
	return operations, nil
}

func surroundZoneForestWithBlackholeZone(zoneForest []*zoneTree, blackholeBodyID context.BodyID) *zoneTree {
	return &zoneTree{
		childrens:  zoneForest,
		baseBodyID: blackholeBodyID,
		operations: []operation{},
	}
}
