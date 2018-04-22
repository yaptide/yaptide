package setup

import (
	"encoding/json"

	"github.com/yaptide/yaptide/pkg/converter/geometry"
)

// DetectorMesh detector.
type DetectorMesh struct {
	Center geometry.Point    `json:"center"`
	Size   geometry.Vec3D    `json:"size"`
	Slices geometry.Vec3DInt `json:"slices"`
}

// MarshalJSON json.Marshaller implementation.
func (d DetectorMesh) MarshalJSON() ([]byte, error) {
	type Alias DetectorMesh
	return json.Marshal(struct {
		Type string `json:"type"`
		Alias
	}{
		Type:  detectorGeometryType.mesh,
		Alias: Alias(d),
	})
}
