package setup

import (
	"encoding/json"
)

// Zone detector used to debug geometry.
type Zones struct {
	Zones []ID `json:"zones"`
}

// MarshalJSON json.Marshaller implementation.
func (z Zones) MarshalJSON() ([]byte, error) {
	type Alias Zones
	return json.Marshal(struct {
		detectorType
		Alias
	}{
		detectorType: zoneScoringDetector,
		Alias:        (Alias)(z),
	})
}
