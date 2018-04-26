package cli

import (
	"os/exec"
)

func setupDependicies() {
	if err := goGetLibrary("gopkg.in/alecthomas/gometalinter.v2"); err != nil {
		log.Error(err)
		return
	}
	if err := goGetLibrary("github.com/codegangsta/gin"); err != nil {
		log.Error(err)
		return
	}
	if err := ensureDeps(backendModule); err != nil {
		log.Error(err.Error())
		return
	}
	if err := ensureNpmDeps(frontendModule); err != nil {
		log.Error(err.Error())
		return
	}
	if err := checkDocker(); err != nil {
		log.Error(err.Error())
		return
	}
}

func checkDocker() error {
	if _, err := exec.LookPath("docker"); err != nil {
		log.Error("You need to install docker to use some of builder functionalities.")
		log.Error(err)
		return err
	}
	log.Info("docker is already installed")
	return nil
}
