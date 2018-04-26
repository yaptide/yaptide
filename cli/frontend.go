package cli

import (
	"fmt"
	"os"
	"os/exec"
)

const frontendModule = "github.com/yaptide/ui"

func startDevFrontend(conf config) (*exec.Cmd, error) {
	log.Info("Starting yaptide/ui ...")
	cmd := exec.Command("npm", "start")
	absolutePath, getPackageErr := getPackagePath(frontendModule)
	if getPackageErr != nil {
		log.Error(getPackageErr)
		return nil, getPackageErr
	}
	cmd.Dir = absolutePath
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	cmd.Env = os.Environ()
	cmd.Env = append(cmd.Env, fmt.Sprintf("BACKEND_PUBLIC_URL=%s", conf.backendPublicURL))
	cmd.Env = append(cmd.Env, fmt.Sprintf("PORT=%d", conf.frontendPort))
	cmd.Env = append(cmd.Env, fmt.Sprintf("FRONTEND_PUBLIC_URL=%s", conf.frontendPublicURL))
	log.Infof("Started frontend [ENV: %s, PORT: %d]", "DEV", conf.frontendPort)
	return cmd, cmd.Start()
}

func ensureNpm() error {
	_, pathErr := exec.LookPath("npm")
	if pathErr == nil {
		return nil
	}
	_, nvmPathErr := exec.LookPath("nvm")
	if nvmPathErr != nil {
		log.Info("Installing nvm")
		cmd := exec.Command(
			"bash",
			"-c",
			"curl -o- https://raw.githubusercontent.com/creationix/nvm/v0.33.10/install.sh | bash",
		)
		runErr := cmd.Run()
		if runErr != nil {
			log.Error(runErr)
			return runErr
		}
	}
	log.Info("Download npm")
	if err := exec.Command("nvm", "install", "8").Run(); err != nil {
		log.Error(err)
		return err
	}
	log.Info("Install npm")
	if err := exec.Command("nvm", "use", "8").Run(); err != nil {
		log.Error(err)
		return err
	}
	if _, err := exec.LookPath("npm"); err != nil {
		log.Errorf("npm install failed %v", err)
		return pathErr
	}
	return nil
}

func ensureNpmDeps(importPath string) error {
	log.Info("ensure npm dependencies")
	npmErr := ensureNpm()
	if npmErr != nil {
		log.Error(npmErr)
		return npmErr
	}
	log.Info("npm install ...")
	cmd := exec.Command("npm", "install")
	absolutePath, getPackageErr := getPackagePath(importPath)
	if getPackageErr != nil {
		log.Error(getPackageErr)
		return getPackageErr
	}
	cmd.Dir = absolutePath
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	if err := cmd.Run(); err != nil {
		log.Error(err)
		return err
	}
	return nil
}

func testFrontend(conf config) error {
	absolutePath, pathErr := getPackagePath(frontendModule)
	if pathErr != nil {
		log.Error(pathErr)
		return pathErr
	}

	cmd := exec.Command("npm", "run", "test")
	cmd.Dir = absolutePath
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	if err := cmd.Run(); err != nil {
		log.Error(err)
		return err
	}
	return nil
}

func lintFrontend(conf config) error {
	absolutePath, pathErr := getPackagePath(frontendModule)
	if pathErr != nil {
		log.Error(pathErr)
		return pathErr
	}

	cmd := exec.Command("npm", "run", "lint")
	cmd.Dir = absolutePath
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	if err := cmd.Run(); err != nil {
		log.Error(err)
		return err
	}
	return nil
}

func checkFrontend(conf config) error {
	absolutePath, pathErr := getPackagePath(frontendModule)
	if pathErr != nil {
		log.Error(pathErr)
		return pathErr
	}

	cmd := exec.Command("npm", "run", "check")
	cmd.Dir = absolutePath
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	if err := cmd.Run(); err != nil {
		log.Error(err)
		return err
	}
	return nil
}
