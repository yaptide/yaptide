package setup

import "encoding/json"

// BodyID is key type in Body map.
type BodyID int64

// Body store Geometry interface described by ID and Name.
type Body struct {
	ID       BodyID       `json:"id"`
	Name     string       `json:"name,omitempty"`
	Geometry BodyGeometry `json:"geometry"`
}

// UnmarshalJSON custom Unmarshal function.
// GeometryType is recognized by geometry/type in json.
func (body *Body) UnmarshalJSON(b []byte) error {
	type rawBody struct {
		ID          BodyID          `json:"id"`
		Name        string          `json:"name,omitempty"`
		GeometryRaw json.RawMessage `json:"geometry"`
	}

	var raw rawBody
	err := json.Unmarshal(b, &raw)
	if err != nil {
		return err
	}
	body.ID = raw.ID
	body.Name = raw.Name

	geometry, err := unmarshalGeometry(raw.GeometryRaw)
	if err != nil {
		return err
	}
	body.Geometry = geometry

	return nil
}
