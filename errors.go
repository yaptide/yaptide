package converter

import (
	"fmt"
)

type makeNewGeneralErrorFuncType = func(message string, formatedvalues ...interface{}) error
type makeNewIDErrorFuncType = func(id interface{}, message string, formatedValues ...interface{}) error

var GeneralMatError = makeNewGeneralErrorFunc("mat.dat")
var MaterialIDError = makeNewIDErrorFunc("Material", "mat.dat")
var GeneralDetectorError = makeNewGeneralErrorFunc("detect.dat")

var BodyIDError = makeNewIDErrorFunc("Body", "geo.dat")
var ZoneIDError = makeNewIDErrorFunc("Zone", "geo.dat")

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
