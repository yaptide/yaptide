package cli

import (
	"os"
	"os/exec"
)

func ensureDeps(importPath string) error {
	log.Infof("dep ensure in %s", importPath)
	cmd := exec.Command("dep", "ensure")
	absolutePath, getPackageErr := getPackagePath(importPath)
	if getPackageErr != nil {
		return getPackageErr
	}
	cmd.Dir = absolutePath
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	return cmd.Run()
}

func goGetLibrary(library string) error {
	log.Infof("go get %s", library)
	cmd := exec.Command("go", "get", "-u", library)
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	return cmd.Run()
}
