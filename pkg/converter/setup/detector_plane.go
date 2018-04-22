package setup

import (
	"encoding/json"

	"github.com/yaptide/converter/geometry"
)

// DetectorPlane detector.
type DetectorPlane struct {
	Point  geometry.Point `json:"point"`
	Normal geometry.Vec3D `json:"normal"`
}

// MarshalJSON json.Marshaller implementation.
func (d DetectorPlane) MarshalJSON() ([]byte, error) {
	type Alias DetectorPlane
	return json.Marshal(struct {
		Type string `json:"type"`
		Alias
	}{
		Type:  detectorGeometryType.plane,
		Alias: Alias(d),
	})
}
