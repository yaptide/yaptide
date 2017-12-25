package detector

import (
	"encoding/json"
	"github.com/yaptide/converter/common"
)

// Plane detector.
type Plane struct {
	Point  common.Point `json:"point"`
	Normal common.Vec3D `json:"normal"`
}

// MarshalJSON json.Marshaller implementation.
func (g Plane) MarshalJSON() ([]byte, error) {
	type Alias Plane
	return json.Marshal(struct {
		detectorType
		Alias
	}{
		detectorType: planeScoringDetector,
		Alias:        (Alias)(g),
	})
}
