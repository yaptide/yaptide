package setup

import (
	"encoding/json"

	"github.com/yaptide/yaptide/pkg/converter/utils"
)

var detectorGeometryType = struct {
	geomap   string
	zone     string
	cylinder string
	mesh     string
	plane    string
}{
	geomap:   "geomap",
	zone:     "zone",
	cylinder: "cylinder",
	mesh:     "mesh",
	plane:    "plane",
}

var detectorGeometryTypeMapping = map[string]func() interface{}{
	detectorGeometryType.geomap:   func() interface{} { return &DetectorGeomap{} },
	detectorGeometryType.zone:     func() interface{} { return &DetectorZones{} },
	detectorGeometryType.mesh:     func() interface{} { return &DetectorMesh{} },
	detectorGeometryType.plane:    func() interface{} { return &DetectorPlane{} },
	detectorGeometryType.cylinder: func() interface{} { return &DetectorCylinder{} },
}

// DetectorID ...
type DetectorID int64

// Detector describes where and what values are scored during simulation.
type Detector struct {
	ID               DetectorID       `json:"id"`
	Name             string           `json:"name"`
	DetectorGeometry DetectorGeometry `json:"detectorGeometry"`
	ScoredParticle   Particle         `json:"particle"`
	Scoring          DetectorScoring  `json:"scoring"`
}

// GeometryType ...
type GeometryType interface{}

// DetectorGeometry ...
type DetectorGeometry struct {
	GeometryType
}

// MarshalJSON ...
func (d DetectorGeometry) MarshalJSON() ([]byte, error) {
	return json.Marshal(d.GeometryType)
}

// UnmarshalJSON ...
func (d *DetectorGeometry) UnmarshalJSON(b []byte) error {
	geometry, err := utils.TypeBasedUnmarshallJSON(b, detectorGeometryTypeMapping)
	if err != nil {
		return err
	}
	d.GeometryType = geometry
	return nil
}
