package main

import (
	"os"
	"strings"

	log "github.com/sirupsen/logrus"
	"github.com/yaptide/worker/config"
	"github.com/yaptide/worker/process"
	"github.com/yaptide/worker/simulation"
)

func main() {
	config := config.Read()
	initLogger(config)
	log.Debugf("Config: %#v", config)

	processRunner := process.CreateRunner()

	simRunner, err := simulation.NewRunner(processRunner)
	if err != nil {
		log.Error(err.Error())
		os.Exit(1)
	}

	log.Debug("simulation.Runner created")
	log.Infof("Available computing libraries: [%s]",
		strings.Join(simRunner.AvailableComputingLibrariesNames(), ", "),
	)

	err = connectAndServe(config, simRunner)
	if err != nil {
		log.Error(err.Error())
		os.Exit(1)
	}
}

func initLogger(config config.Config) {
	log.SetFormatter(&log.TextFormatter{FullTimestamp: true})

	level, err := log.ParseLevel(config.LoggingLevel)
	if err != nil {
		panic(err)
	}
	log.SetLevel(level)
}
