package setup

import "encoding/json"

// MaterialVoxel TODO
type MaterialVoxel struct {
	_ int // mock to fix memory alignment issue.
}

// MarshalJSON json.Marshaller implementation.
func (v MaterialVoxel) MarshalJSON() ([]byte, error) {
	type Alias MaterialVoxel
	return json.Marshal(struct {
		Type string `json:"type"`
		Alias
	}{
		Type:  materialType.voxel,
		Alias: (Alias)(v),
	})
}
