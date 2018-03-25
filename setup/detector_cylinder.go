package setup

import (
	"encoding/json"

	"github.com/yaptide/converter/common"
)

// Cylinder is detector with cylindrical shape directed along z-axis.
type DetectorCylinder struct {
	Radius common.Range               `json:"radius"`
	Angle  common.Range               `json:"angle"`
	ZValue common.Range               `json:"zValue"`
	Slices common.Vec3DCylindricalInt `json:"slices"`
}

// MarshalJSON json.Marshaller implementation.
func (g DetectorCylinder) MarshalJSON() ([]byte, error) {
	type Alias DetectorCylinder
	return json.Marshal(struct {
		detectorType
		Alias
	}{
		detectorType: cylindricalScoringDetector,
		Alias:        (Alias)(g),
	})
}
