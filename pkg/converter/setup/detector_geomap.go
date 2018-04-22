package setup

import (
	"encoding/json"

	"github.com/yaptide/yaptide/pkg/converter/geometry"
)

// DetectorGeomap detector used to debug geometry.
type DetectorGeomap struct {
	Center geometry.Point    `json:"center"`
	Size   geometry.Vec3D    `json:"size"`
	Slices geometry.Vec3DInt `json:"slices"`
}

// MarshalJSON json.Marshaller implementation.
func (d DetectorGeomap) MarshalJSON() ([]byte, error) {
	type Alias DetectorGeomap
	return json.Marshal(struct {
		Type string `json:"type"`
		Alias
	}{
		Type:  detectorGeometryType.geomap,
		Alias: Alias(d),
	})
}
