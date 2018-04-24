package file

import (
	"fmt"
	"path"

	conf "github.com/yaptide/yaptide/config"
)

const (
	shieldBinaryName = "shieldhit"
	beamDatFile      = "beam.dat"
	detectorsDatFile = "detect.dat"
	geometryDatFile  = "geo.dat"
	materialsDatFile = "mat.dat"
)

func generateShieldPath(workDir string) []string {
	cmd := []string{
		shieldBinaryName,
		fmt.Sprintf("--beamfile=%s", path.Join(workDir, beamDatFile)),
		fmt.Sprintf("--geofile=%s", path.Join(workDir, geometryDatFile)),
		fmt.Sprintf("--matfile=%s", path.Join(workDir, materialsDatFile)),
		fmt.Sprintf("--detectfile=%s", path.Join(workDir, detectorsDatFile)),
	}
	return cmd
}

// SetupShieldRunner ...
func SetupShieldRunner(config *conf.Config) *Runner {
	return SetupRunner(config, generateShieldPath)
}
