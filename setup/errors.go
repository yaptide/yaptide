package setup

import "fmt"

type Error struct {
	*MaterialsErr
	*DetectorsErr
	*GeometryErr
	*BeamErr

	CommonError
}

type CommonError struct {
	HasCriticalError bool `json:"hasCriticalErrors"`
	HasError         bool `json:"hasErrors"`
	HasWarning       bool `json:"hasWarnings"`
}

func (e Error) Error() string {
	return fmt.Sprintf("%+v", e)
}

type MaterialsErr struct {
	Materials         map[int64]error `json:"materials"`
	MaterialGlobalErr error           `json:"rootMaterial"`
	CommonError       `json:"-"`
}

type DetectorsErr struct {
	Detectors         map[int64]error `json:"detectors"`
	DetectorGlobalErr error           `json:"rootDetector"`
	CommonError       `json:"-"`
}

type GeometryErr struct {
	Bodies      map[int64]error `json:"bodies"`
	Zones       map[int64]error `json:"zones"`
	BodyGlobErr error           `json:"rootBody"`
	ZoneGlobErr error           `json:"rootZone"`
	CommonError `json:"-"`
}

type BeamErr struct {
	Beam        map[string]error `json:"beam"`
	Options     map[string]error `json:"options"`
	CommonError `json:"-"`
}

type E map[string]error

func (e E) Error() string {
	return fmt.Sprintf("%+v", e)
}
