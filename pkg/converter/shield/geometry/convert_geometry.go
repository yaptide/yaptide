package geometry

import (
	"github.com/yaptide/yaptide/pkg/converter"
	"github.com/yaptide/yaptide/pkg/converter/setup"
	"github.com/yaptide/yaptide/pkg/converter/shield/material"
)

// Geometry represent ready to serialize data for geo.dat file.
type Geometry struct {
	Bodies              []Body
	Zones               []Zone
	ZoneToMaterialPairs []ZoneToMaterial
}

// ConvertSetupGeometry ...
func ConvertSetupGeometry(
	bodyMap converter.BodyMap,
	zoneMap converter.ZoneMap,
	materialIDToShield map[setup.MaterialID]material.ShieldID,
) (Geometry, map[setup.BodyID]ShieldBodyID, error) {
	bodies, bodyIDToShield, err := convertSetupBodies(bodyMap)
	if err != nil {
		return Geometry{}, bodyIDToShield, err
	}

	bodiesWithBlackhole, blackholeBodyID, err := appendBlackholeBody(bodies)
	if err != nil {
		return Geometry{}, bodyIDToShield, err
	}

	zoneForest, err := convertSetupZonesToZoneTreeForest(zoneMap, materialIDToShield, bodyIDToShield)
	if err != nil {
		return Geometry{}, bodyIDToShield, err
	}

	root := surroundZoneForestWithBlackholeZone(zoneForest, blackholeBodyID)

	zones, zoneToMaterialPairs, err := convertTreeToZones(root)
	if err != nil {
		return Geometry{}, bodyIDToShield, err
	}

	return Geometry{
		Bodies:              bodiesWithBlackhole,
		Zones:               zones,
		ZoneToMaterialPairs: zoneToMaterialPairs,
	}, bodyIDToShield, nil

}
