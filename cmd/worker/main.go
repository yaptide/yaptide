package main

import (
	"os"

	log "github.com/sirupsen/logrus"
	"github.com/yaptide/yaptide/worker/config"
	"github.com/yaptide/yaptide/worker/process"
	"github.com/yaptide/yaptide/worker/simulation"
	"github.com/yaptide/yaptide/worker/wsclient"
)

func main() {
	config := config.Read()
	initLogger(config)
	log.Debugf("Config: %#v", config)

	processRunner := process.NewRunner()
	simulationRunner, err := simulation.NewRunner(processRunner)
	if err != nil {
		log.Error(err.Error())
		os.Exit(1)
	}

	log.Infof("Available computing libraries: ")
	for _, name := range simulationRunner.AvailableComputingLibrariesNames() {
		log.Infof("\t\"%s\"", name)
	}

	err = wsclient.ConnectAndServe(config, simulationRunner)
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
