package setup

import "encoding/json"

// DetectorZones ...
type DetectorZones struct {
	Zones []DetectorID `json:"zones"`
}

// MarshalJSON json.Marshaller implementation.
func (d DetectorZones) MarshalJSON() ([]byte, error) {
	type Alias DetectorZones
	return json.Marshal(struct {
		Type string `json:"type"`
		Alias
	}{
		Type:  detectorGeometryType.zone,
		Alias: Alias(d),
	})
}
