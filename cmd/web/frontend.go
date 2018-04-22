package builder

import (
	"fmt"
	"log"
	"os"
	"os/exec"
)

const frontendModule = "github.com/yaptide/ui"

func startDevFrontend(conf config) (*exec.Cmd, error) {
	cmd := exec.Command("npm", "start")
	absolutePath, getPackageErr := getPackagePath(frontendModule)
	if getPackageErr != nil {
		return nil, getPackageErr
	}
	cmd.Dir = absolutePath
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	cmd.Env = os.Environ()
	cmd.Env = append(cmd.Env, fmt.Sprintf("YAPTIDE_BACKEND_PUBLIC_URL=%s", conf.backendPublicUrl))
	cmd.Env = append(cmd.Env, fmt.Sprintf("YAPTIDE_FRONTEND_PORT=%d", conf.frontendPort))
	cmd.Env = append(cmd.Env, fmt.Sprintf("YAPTIDE_FRONTEND_PUBLIC_URL=%s", conf.frontendPublicUrl))
	log.Print(cmd.Env)
	return cmd, cmd.Start()
}

func ensureNpm() error {
	_, pathErr := exec.LookPath("npm")
	if pathErr != nil {
		log.Println("Install nvm")
		cmd := exec.Command(
			"bash",
			"-c",
			"curl -o- https://raw.githubusercontent.com/creationix/nvm/v0.33.8/install.sh | bash",
		)
		runErr := cmd.Run()
		if runErr != nil {
			return runErr
		}
		log.Println("Download npm")
		if err := exec.Command("nvm", "install", "8").Run(); err != nil {
			return err
		}
		log.Println("Install npm")
		if err := exec.Command("nvm", "use", "8").Run(); err != nil {
			return err
		}
		return nil
	}
	return nil
}

func ensureNpmDeps(importPath string) error {
	npmErr := ensureNpm()
	if npmErr != nil {
		return npmErr
	}
	cmd := exec.Command("bash", "-c", "npm", "install")
	absolutePath, getPackageErr := getPackagePath(importPath)
	if getPackageErr != nil {
		return getPackageErr
	}
	cmd.Dir = absolutePath
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	return cmd.Run()
}
