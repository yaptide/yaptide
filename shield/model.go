package shield

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
	MapMaterialID           map[MaterialID]setup.ID
	MapBodyID               map[BodyID]setup.ID
	MapFilenameToDetectorID map[string]setup.ID
}

// NewSerializationContext constructor.
func NewSerializationContext() *SerializationContext {
	return &SerializationContext{
		MapMaterialID:           map[MaterialID]setup.ID{},
		MapBodyID:               map[BodyID]setup.ID{},
		MapFilenameToDetectorID: map[string]setup.ID{},
	}
}
