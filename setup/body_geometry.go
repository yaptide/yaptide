package setup

import (
	"encoding/json"

	"github.com/yaptide/converter/geometry"
)

// SphereBody represent sphere with given radius in space.
type SphereBody struct {
	Center geometry.Point `json:"center"`
	Radius float64        `json:"radius"`
}

// MarshalJSON json.Marshaller implementaion.
func (s SphereBody) MarshalJSON() ([]byte, error) {
	type Alias SphereBody
	return json.Marshal(struct {
		Type string `json:"type"`
		Alias
	}{
		Type:  bodyType.sphere,
		Alias: Alias(s),
	})
}

// CuboidBody represent cuboid of given sizes in a space.
type CuboidBody struct {
	Center geometry.Point `json:"center"`
	Size   geometry.Vec3D `json:"size"`
}

// MarshalJSON json.Marshaller implementaion.
func (c CuboidBody) MarshalJSON() ([]byte, error) {
	type Alias CuboidBody
	return json.Marshal(struct {
		Type string `json:"type"`
		Alias
	}{
		Type:  bodyType.cuboid,
		Alias: Alias(c),
	})
}

// CylinderBody represent cylinder of given sizes in a space.
type CylinderBody struct {
	Center geometry.Point `json:"baseCenter"`
	Height float64        `json:"height"`
	Radius float64        `json:"radius"`
}

// MarshalJSON json.Marshaller implementaion.
func (c CylinderBody) MarshalJSON() ([]byte, error) {
	type Alias CylinderBody
	return json.Marshal(struct {
		Type string `json:"type"`
		Alias
	}{
		Type:  bodyType.cylinder,
		Alias: Alias(c),
	})
}
