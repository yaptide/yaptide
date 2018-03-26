package setup

import (
	"encoding/json"

	"github.com/yaptide/converter/common"
)

// DetectorGeomap detector used to debug geometry.
type DetectorGeomap struct {
	Center common.Point    `json:"center"`
	Size   common.Vec3D    `json:"size"`
	Slices common.Vec3DInt `json:"slices"`
}

// MarshalJSON json.Marshaller implementation.
func (g DetectorGeomap) MarshalJSON() ([]byte, error) {
	type Alias DetectorGeomap
	return json.Marshal(struct {
		detectorType
		Alias
	}{
		detectorType: geomapDetector,
		Alias:        (Alias)(g),
	})
}
