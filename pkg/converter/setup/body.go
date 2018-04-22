package setup

import (
	"encoding/json"

	"github.com/yaptide/yaptide/pkg/converter/utils"
)

var bodyType = struct {
	cuboid   string
	cylinder string
	sphere   string
}{
	cuboid:   "cuboid",
	cylinder: "cylinder",
	sphere:   "sphere",
}

var bodyTypeMapping = map[string]func() interface{}{
	bodyType.cuboid:   func() interface{} { return &CuboidBody{} },
	bodyType.cylinder: func() interface{} { return &CylinderBody{} },
	bodyType.sphere:   func() interface{} { return &SphereBody{} },
}

// BodyID is key type in Body map.
type BodyID int64

// Body store Geometry interface described by ID and Name.
type Body struct {
	ID       BodyID       `json:"id"`
	Name     string       `json:"name,omitempty"`
	Geometry BodyGeometry `json:"geometry"`
}

// BodyGeometry ...
type BodyGeometry struct {
	BodyType
}

// BodyType ...
type BodyType interface{}

// MarshalJSON ...
func (g BodyGeometry) MarshalJSON() ([]byte, error) {
	return json.Marshal(g.BodyType)
}

// UnmarshalJSON ...
func (g *BodyGeometry) UnmarshalJSON(b []byte) error {
	body, err := utils.TypeBasedUnmarshallJSON(b, bodyTypeMapping)
	if err != nil {
		return err
	}
	g.BodyType = body
	return nil
}
