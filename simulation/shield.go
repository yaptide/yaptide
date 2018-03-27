package simulation

import (
	"fmt"
	"os/exec"
	"path"
	"strings"
)

const (
	shieldBinaryName = "shieldhit"
	beamDatFile      = "beam.dat"
	detectorsDatFile = "detect.dat"
	geometryDatFile  = "geo.dat"
	materialsDatFile = "mat.dat"
)

type shieldHIT12A struct{}

func (s shieldHIT12A) Name() string {
	outByte, _ := exec.Command(shieldBinaryName, "--version").Output()

	out := string(outByte)
	out = strings.Replace(out, "\n", ", ", -1)
	out = out[:len(out)-2]
	return strings.TrimSpace(out)
}

func (s shieldHIT12A) CreateCMDFunc(workingDirPath string) *exec.Cmd {
	return exec.Command(shieldBinaryName,
		fmt.Sprintf("--beamfile=%s", path.Join(workingDirPath, beamDatFile)),
		fmt.Sprintf("--geofile=%s", path.Join(workingDirPath, geometryDatFile)),
		fmt.Sprintf("--matfile=%s", path.Join(workingDirPath, materialsDatFile)),
		fmt.Sprintf("--detectfile=%s", path.Join(workingDirPath, detectorsDatFile)),
	)
}

func (s shieldHIT12A) IsWorking() bool {
	err := exec.Command(shieldBinaryName).Run()
	return err != nil
}
