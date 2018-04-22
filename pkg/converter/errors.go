package converter

import (
	"fmt"
)

type makeNewGeneralErrorFuncType = func(message string, formatedvalues ...interface{}) error
type makeNewIDErrorFuncType = func(
	id interface{}, message string, formatedValues ...interface{},
) error

// GeneralMatError ...
var GeneralMatError = makeNewGeneralErrorFunc("mat.dat")

// MaterialIDError ...
var MaterialIDError = makeNewIDErrorFunc("Material", "mat.dat")

// GeneralDetectorError ...
var GeneralDetectorError = makeNewGeneralErrorFunc("detect.dat")

// BodyIDError ...
var BodyIDError = makeNewIDErrorFunc("Body", "geo.dat")

// ZoneIDError ...
var ZoneIDError = makeNewIDErrorFunc("Zone", "geo.dat")

// DetectorIDError ...
var DetectorIDError = makeNewIDErrorFunc("Detector", "detect.dat")

func makeNewGeneralErrorFunc(serializedFileName string) makeNewGeneralErrorFuncType {
	return func(message string, formatedValues ...interface{}) error {
		return fmt.Errorf("[serializer] "+serializedFileName+": "+message, formatedValues...)
	}
}

func makeNewIDErrorFunc(modelName, serializedFileName string) makeNewIDErrorFuncType {
	return func(id interface{}, message string, formatedValues ...interface{}) error {
		header := fmt.Sprintf("[serializer] %s{Id: %v} -> %s: ", modelName, id, serializedFileName)
		return fmt.Errorf(header+message, formatedValues...)
	}
}
