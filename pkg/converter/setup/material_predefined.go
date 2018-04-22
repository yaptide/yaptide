package setup

import "encoding/json"

// MaterialPredefined material type - choose material definition
// from predefined material list by name.
type MaterialPredefined struct {
	PredefinedID string `json:"predefinedId"`

	// Density of the medium in g/cm³ - optional.
	Density float64 `json:"density,omitempty"`

	// State of matter - optional
	StateOfMatter StateOfMatter `json:"stateOfMatter,omitempty"`

	// Load stopping power from external file.
	LoadExternalStoppingPower bool `json:"loadExternalStoppingPower,omitempty"`
}

// MarshalJSON json.Marshaller implementation.
func (p MaterialPredefined) MarshalJSON() ([]byte, error) {
	type Alias MaterialPredefined
	return json.Marshal(struct {
		Type string `json:"type"`
		Alias
	}{
		Type:  materialType.predefined,
		Alias: (Alias)(p),
	})
}
