package setup

import (
	"github.com/yaptide/converter/setup"
	"github.com/yaptide/converter/setup/material"
	"github.com/yaptide/converter/shield"
)

// Geometry represent ready to serialize data for geo.dat file.
type Geometry struct {
	Bodies              []Body
	Zones               []Zone
	ZoneToMaterialPairs []ZoneToMaterial
}

func convertSetupGeometry(bodyMap setup.BodyMap, zoneMap setup.ZoneMap, materialIDToShield map[material.ID]shield.MaterialID, simContext *shield.SerializationContext) (Geometry, error) {
	bodies, bodyIDToShield, err := convertSetupBodies(bodyMap, simContext)
	if err != nil {
		return Geometry{}, err
	}

	bodiesWithBlackhole, blackholeBodyID, err := appendBlackholeBody(bodies)
	if err != nil {
		return Geometry{}, err
	}

	zoneForest, err := convertSetupZonesToZoneTreeForest(zoneMap, materialIDToShield, bodyIDToShield)
	if err != nil {
		return Geometry{}, err
	}

	root := surroundZoneForestWithBlackholeZone(zoneForest, blackholeBodyID)

	zones, zoneToMaterialPairs, err := convertTreeToZones(root)
	if err != nil {
		return Geometry{}, err
	}

	return Geometry{
		Bodies:              bodiesWithBlackhole,
		Zones:               zones,
		ZoneToMaterialPairs: zoneToMaterialPairs,
	}, nil

}
