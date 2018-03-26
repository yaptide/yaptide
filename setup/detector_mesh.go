package setup

import (
	"encoding/json"

	"github.com/yaptide/converter/common"
)

// DetectorMesh detector.
type DetectorMesh struct {
	Center common.Point    `json:"center"`
	Size   common.Vec3D    `json:"size"`
	Slices common.Vec3DInt `json:"slices"`
}

// MarshalJSON json.Marshaller implementation.
func (m DetectorMesh) MarshalJSON() ([]byte, error) {
	type Alias DetectorMesh
	return json.Marshal(struct {
		detectorType
		Alias
	}{
		detectorType: meshScoringDetector,
		Alias:        (Alias)(m),
	})
}
