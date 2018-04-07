package setup

import (
	"encoding/json"

	"github.com/yaptide/converter/utils"
)

var materialType = struct {
	predefined string
	compound   string
	voxel      string
}{
	predefined: "predefined",
	compound:   "compound",
	voxel:      "voxel",
}

var materialTypeMapping = map[string]func() interface{}{
	materialType.predefined: func() interface{} { return &MaterialPredefined{} },
	materialType.compound:   func() interface{} { return &MaterialCompound{} },
	materialType.voxel:      func() interface{} { return &MaterialVoxel{} },
}

// MaterialID ...
type MaterialID int64

// Material defines the zone material that is used in the simulation.
type Material struct {
	ID    MaterialID    `json:"id"`
	Specs MaterialSpecs `json:"specs"`
}

// MaterialSpecs ...
type MaterialSpecs struct {
	MaterialType
}

// MaterialType ...
type MaterialType interface{}

// MarshalJSON ...
func (m MaterialSpecs) MarshalJSON() ([]byte, error) {
	return json.Marshal(m.MaterialType)
}

// UnmarshalJSON custom Unmarshal function.
// material.Type is recognized by material/type in json.
func (m *MaterialSpecs) UnmarshalJSON(b []byte) error {
	materialInfo, err := utils.TypeBasedUnmarshallJSON(b, materialTypeMapping)
	if err != nil {
		return err
	}
	m.MaterialType = materialInfo
	return nil
}
