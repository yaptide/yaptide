package builder

import (
	"log"
	"os/exec"
)

func setupDependicies() {
	if err := ensureDeps(backendModule); err != nil {
		log.Println(err.Error())
		return
	}
	if err := ensureDeps(converterModule); err != nil {
		log.Println(err.Error())
		return
	}
	if err := ensureNpmDeps(frontendModule); err != nil {
		log.Println(err.Error())
		return
	}
	if err := checkDocker(); err != nil {
		log.Println(err.Error())
		return
	}
}

func checkDocker() error {
	if _, err := exec.LookPath("docker"); err != nil {
		log.Print("You need to install docker to use some of builder functionalities.")
		return err
	}
	return nil
}
