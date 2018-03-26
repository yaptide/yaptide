package setup

import (
	"encoding/json"

	"github.com/yaptide/converter/common"
)

// DetectorPlane detector.
type DetectorPlane struct {
	Point  common.Point `json:"point"`
	Normal common.Vec3D `json:"normal"`
}

// MarshalJSON json.Marshaller implementation.
func (g DetectorPlane) MarshalJSON() ([]byte, error) {
	type Alias DetectorPlane
	return json.Marshal(struct {
		detectorType
		Alias
	}{
		detectorType: planeScoringDetector,
		Alias:        (Alias)(g),
	})
}
