package shield

import (
	"github.com/yaptide/yaptide/pkg/converter/log"
	"github.com/yaptide/yaptide/pkg/converter/shield/beam"
	"github.com/yaptide/yaptide/pkg/converter/shield/detector"
	"github.com/yaptide/yaptide/pkg/converter/shield/geometry"
	"github.com/yaptide/yaptide/pkg/converter/shield/material"
)

// SerializeData ...
func SerializeData(data RawShieldSetup) map[string]string {
	log.Debug("[Serializer] data %+v", data)
	files := map[string]string{}

	for fileName, serializeFunc := range map[string]func() string{
		materialsDatFile: func() string { return material.Serialize(data.Materials) },
		geometryDatFile:  func() string { return geometry.Serialize(data.Geometry) },
		detectorsDatFile: func() string { return detector.Serialize(data.Detectors) },
		beamDatFile:      func() string { return beam.Serialize(data.Beam, data.Options) },
	} {
		serializeOutput := serializeFunc()
		files[fileName] = serializeOutput
	}

	log.Debug("Files:\n")
	for filename, content := range files {
		log.Debug("%s:\n%s\n\n", filename, content)
	}

	return files
}
