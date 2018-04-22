package shield

import (
	"github.com/yaptide/converter/setup"
	"github.com/yaptide/converter/shield/geometry"
	"github.com/yaptide/converter/shield/material"
)

// SerializationContext is struct used to recover data lost in process of
// serializing simulation data.
type SerializationContext struct {
	MapMaterialID           map[material.ShieldID]setup.MaterialID
	MapBodyID               map[geometry.ShieldBodyID]setup.BodyID
	MapFilenameToDetectorID map[string]setup.DetectorID
}

// NewSerializationContext constructor.
func NewSerializationContext() SerializationContext {
	return SerializationContext{
		MapMaterialID:           map[material.ShieldID]setup.MaterialID{},
		MapBodyID:               map[geometry.ShieldBodyID]setup.BodyID{},
		MapFilenameToDetectorID: map[string]setup.DetectorID{},
	}
}
