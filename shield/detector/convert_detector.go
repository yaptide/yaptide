package detector

import (
	"bytes"
	"fmt"
	"sort"
	"unicode"

	"github.com/yaptide/converter"
	"github.com/yaptide/converter/common"
	"github.com/yaptide/converter/geometry"
	"github.com/yaptide/converter/setup"
	"github.com/yaptide/converter/shield/mapping"
	"github.com/yaptide/converter/shield/material"
)

// Detector represent setup.Detector,
type Detector struct {
	ScoringType string

	// Argument can be int64, float64 or string.
	Arguments []interface{}
}

func ConvertSetupDetectors(
	detectorsMap converter.DetectorMap,
	materialIDToShield map[setup.MaterialID]material.ShieldID,
) ([]Detector, map[string]setup.DetectorID, error) {
	result := []Detector{}
	detectIds := []setup.DetectorID{}
	for k := range detectorsMap {
		detectIds = append(detectIds, k)
	}
	sort.SliceStable(detectIds, func(i, j int) bool { return detectIds[i] < detectIds[j] })

	detectorConverter := detectorConverter{materialIDToShield}

	uniqNameSet := map[string]setup.DetectorID{}
	mapFilenameToDetectorID := map[string]setup.DetectorID{}
	for n, id := range detectIds {
		setupDetector := detectorsMap[id]

		duplicateID, foundDuplicate := uniqNameSet[setupDetector.Name]
		if foundDuplicate {
			return nil, uniqNameSet,
				converter.GeneralDetectorError(
					"Found name duplicates: \"%s\" for detector Ids: %d and %d",
					setupDetector.Name, id, duplicateID,
				)
		}
		uniqNameSet[setupDetector.Name] = setupDetector.ID

		filename := createDetectorFileName(setupDetector.Name, n)
		mapFilenameToDetectorID[filename] = setupDetector.ID

		detector, err := detectorConverter.convertDetector(&setupDetector, filename)
		if err != nil {
			return nil, nil, err
		}

		result = append(result, detector)
	}
	return result, mapFilenameToDetectorID, nil
}

type detectorConverter struct {
	materialIDToShield map[setup.MaterialID]material.ShieldID
}

func (d detectorConverter) convertDetector(detect *setup.Detector, filename string) (Detector, error) {
	switch geo := detect.DetectorGeometry.(type) {
	case setup.DetectorGeomap:
		return Detector{}, converter.GeneralDetectorError("Geomap detector serialization not implemented")
	case setup.DetectorZones:
		return Detector{}, converter.GeneralDetectorError("Zone detector serialization not implemented")

	case setup.DetectorCylinder:
		return d.convertStandardGeometryDetector(detect, filename)
	case setup.DetectorMesh:
		return d.convertStandardGeometryDetector(detect, filename)
	case setup.DetectorPlane:
		return d.convertStandardGeometryDetector(detect, filename)

	default:
		return Detector{}, converter.DetectorIDError(detect.ID, "Unkown detector type: %T", geo)
	}
}

func (d detectorConverter) convertStandardGeometryDetector(detect *setup.Detector, filename string) (Detector, error) {
	var newDetector Detector

	switch geo := detect.DetectorGeometry.(type) {
	case setup.DetectorCylinder:
		newDetector = Detector{
			ScoringType: "CYL",
			Arguments: []interface{}{
				geo.Radius.Min,
				geo.Angle.Min,
				geo.ZValue.Min,
				geo.Radius.Max,
				geo.Angle.Max,
				geo.ZValue.Max,

				geo.Slices.Radius,
				geo.Slices.Angle,
				geo.Slices.Z,
			},
		}
	case setup.DetectorMesh:
		xMin, xMax := geometry.CenterAndSizeToMinAndMax(geo.Center.X, geo.Size.Y)
		yMin, yMax := geometry.CenterAndSizeToMinAndMax(geo.Center.Y, geo.Size.Y)
		zMin, zMax := geometry.CenterAndSizeToMinAndMax(geo.Center.Z, geo.Size.Z)
		newDetector = Detector{
			ScoringType: "MSH",
			Arguments: []interface{}{
				xMin,
				yMin,
				zMin,
				xMax,
				yMax,
				zMax,

				geo.Slices.X,
				geo.Slices.Y,
				geo.Slices.Z,
			},
		}
	case setup.DetectorPlane:
		newDetector = Detector{
			ScoringType: "PLANE",
			Arguments: []interface{}{
				geo.Point.X,
				geo.Point.Y,
				geo.Point.Z,
				geo.Normal.X,
				geo.Normal.Y,
				geo.Normal.Z,
				"",
				"",
				"",
			},
		}

	}

	particleInShieldFormat, err := mapping.ParticleToShield(detect.ScoredParticle)
	if err != nil {
		return Detector{}, converter.DetectorIDError(detect.ID, "%s", err.Error())
	}

	scoringInShield, err := mapping.ScoringToShield(detect.ScoringType)
	if err != nil {
		return Detector{}, converter.DetectorIDError(detect.ID, "%s", err.Error())
	}

	newDetector.Arguments = append(newDetector.Arguments,
		particleInShieldFormat,
		scoringInShield,
		filename,
	)

	newDetector.Arguments, err = d.appendHeavyIonOrLetfluCard(newDetector.Arguments, detect.ScoredParticle, detect.ScoringType)
	if err != nil {
		return Detector{}, converter.DetectorIDError(detect.ID, "%s", err.Error())
	}
	return newDetector, nil
}

// TODO: we need A and Z if partile is not HeavyIon and scoring is LetTypeScoring
func (d detectorConverter) appendHeavyIonOrLetfluCard(arguments []interface{}, particle common.Particle, scoringType setup.ScoringType) ([]interface{}, error) {
	switch part := particle.(type) {
	case common.HeavyIon:
		arguments = append(arguments, part.NucleonsCount, part.Charge)
		switch scoring := scoringType.(type) {
		case setup.LetTypeScoring:
			material, found := d.materialIDToShield[scoring.Material]
			if !found {
				return nil, fmt.Errorf("Can not found Material{ID: %d} for LetTypeScoring", scoring.Material)
			}
			arguments = append(arguments, int64(material))
		default:
			arguments = append(arguments, "")
		}
		return append(arguments, "", "", ""), nil
	default:
		return arguments, nil
	}
}

func createDetectorFileName(name string, detectorN int) string {
	buff := &bytes.Buffer{}

	for _, c := range name {
		switch {
		case unicode.IsDigit(c):
			buff.WriteRune(c)
		case c <= unicode.MaxASCII && unicode.IsLetter(c):
			buff.WriteRune(unicode.ToLower(c))
		default:
			buff.WriteString("_")
		}
	}

	fmt.Fprintf(buff, "%d", detectorN)
	return buff.String()
}
