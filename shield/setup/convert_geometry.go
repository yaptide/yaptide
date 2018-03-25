package setup

import (
	"github.com/yaptide/converter"
	"github.com/yaptide/converter/setup"
	"github.com/yaptide/converter/shield/context"
)

// Geometry represent ready to serialize data for geo.dat file.
type Geometry struct {
	Bodies              []Body
	Zones               []Zone
	ZoneToMaterialPairs []ZoneToMaterial
}

func convertSetupGeometry(bodyMap converter.BodyMap, zoneMap converter.ZoneMap, materialIDToShield map[setup.ID]context.MaterialID, simContext *context.SerializationContext) (Geometry, error) {
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
