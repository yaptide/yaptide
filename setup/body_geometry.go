package setup

import (
	"encoding/json"
	"fmt"

	"github.com/yaptide/converter/common"
)

// BodyGeometry is a variant type, which represent different geometries used in simulations.
// It must implement json.Marshaler to marshal geometry type dependant on BodyGeometry implementation type.
type BodyGeometry interface {
	json.Marshaler
}

type geometryType struct {
	Type string `json:"type"`
}

var (
	sphereType   = geometryType{"sphere"}
	cuboidType   = geometryType{"cuboid"}
	cylinderType = geometryType{"cylinder"}
)

func unmarshalGeometry(b json.RawMessage) (BodyGeometry, error) {
	var geoType geometryType
	err := json.Unmarshal(b, &geoType)
	if err != nil {
		return nil, err
	}

	switch geoType {
	case sphereType:
		sphere := SphereBody{}
		err = json.Unmarshal(b, &sphere)
		if err != nil {
			return nil, err
		}
		return sphere, nil
	case cuboidType:
		cuboid := CuboidBody{}
		err = json.Unmarshal(b, &cuboid)
		if err != nil {
			return nil, err
		}
		return cuboid, nil
	case cylinderType:
		cylinder := CylinderBody{}
		err = json.Unmarshal(b, &cylinder)
		if err != nil {
			return nil, err
		}
		return cylinder, nil

	default:
		return nil, fmt.Errorf("Can not Unmarshal \"%s\" GeometryType", geoType.Type)
	}
}

// SphereBody represent sphere with given radius in space.
type SphereBody struct {
	Center common.Point `json:"center"`
	Radius float64      `json:"radius"`
}

// MarshalJSON json.Marshaller implementaion.
func (s SphereBody) MarshalJSON() ([]byte, error) {
	type Alias SphereBody
	return json.Marshal(struct {
		geometryType
		Alias
	}{
		geometryType: sphereType,
		Alias:        (Alias)(s),
	})
}

// CuboidBody represent cuboid of given sizes in a space.
type CuboidBody struct {
	Center common.Point `json:"center"`
	Size   common.Vec3D `json:"size"`
}

// MarshalJSON json.Marshaller implementaion.
func (c CuboidBody) MarshalJSON() ([]byte, error) {
	type Alias CuboidBody
	return json.Marshal(struct {
		geometryType
		Alias
	}{
		geometryType: cuboidType,
		Alias:        (Alias)(c),
	})
}

// CylinderBody represent cylinder of given sizes in a space.
type CylinderBody struct {
	Center common.Point `json:"baseCenter"`
	Height float64      `json:"height"`
	Radius float64      `json:"radius"`
}

// MarshalJSON json.Marshaller implementaion.
func (c CylinderBody) MarshalJSON() ([]byte, error) {
	type Alias CylinderBody
	return json.Marshal(struct {
		geometryType
		Alias
	}{
		geometryType: cylinderType,
		Alias:        (Alias)(c),
	})
}
