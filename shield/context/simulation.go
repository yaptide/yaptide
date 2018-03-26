package context

import (
	"github.com/yaptide/converter/setup"
)

// MaterialID used directly in shield input files.
type MaterialID int

// BodyID used directly in shield input files.
type BodyID int

// ZoneID used directly in shield input files.
type ZoneID int

// SerializationContext is struct used to recover data lost in process of serializing simulation data.
type SerializationContext struct {
	MapMaterialID           map[MaterialID]setup.MaterialID
	MapBodyID               map[BodyID]setup.BodyID
	MapFilenameToDetectorID map[string]setup.DetectorID
}

// NewSerializationContext constructor.
func NewSerializationContext() SerializationContext {
	return SerializationContext{
		MapMaterialID:           map[MaterialID]setup.MaterialID{},
		MapBodyID:               map[BodyID]setup.BodyID{},
		MapFilenameToDetectorID: map[string]setup.DetectorID{},
	}
}
