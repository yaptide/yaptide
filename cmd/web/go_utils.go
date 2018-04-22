package builder

import (
	"os"
	"os/exec"
)

func ensureDeps(importPath string) error {
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
