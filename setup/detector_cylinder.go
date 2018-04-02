package setup

import (
	"encoding/json"

	"github.com/yaptide/converter/geometry"
)

// Cylinder is detector with cylindrical shape directed along z-axis.
type DetectorCylinder struct {
	Radius geometry.Range               `json:"radius"`
	Angle  geometry.Range               `json:"angle"`
	ZValue geometry.Range               `json:"zValue"`
	Slices geometry.Vec3DCylindricalInt `json:"slices"`
}

// MarshalJSON json.Marshaller implementation.
func (d DetectorCylinder) MarshalJSON() ([]byte, error) {
	type Alias DetectorCylinder
	return json.Marshal(struct {
		Type string `json:"type"`
		Alias
	}{
		Type:  detectorGeometryType.cylinder,
		Alias: Alias(d),
	})
}
