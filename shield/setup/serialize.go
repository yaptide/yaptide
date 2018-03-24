package setup

import (
	"github.com/yaptide/converter/log"
)

func SerializeData(data RawShieldSetup) map[string]string {
	log.Debug("[Serializer] data %+v", data)
	files := map[string]string{}

	for fileName, serializeFunc := range map[string]func() string{
		materialsDatFile: func() string { return serializeMat(data.Materials) },
		geometryDatFile:  func() string { return serializeGeo(data.Geometry) },
		detectorsDatFile: func() string { return serializeDetect(data.Detectors) },
		beamDatFile:      func() string { return serializeBeam(data.Beam, data.Options) },
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
