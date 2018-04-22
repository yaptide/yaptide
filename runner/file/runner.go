// Package file implements mechanism of starting and supervising simulations. Simulations are started by running binary configured using config files.
package file

import (
	"fmt"

	conf "github.com/yaptide/yaptide/config"
	"github.com/yaptide/yaptide/model"
)

var log = conf.NamedLogger("file_runner")

const (
	maxNumberOfPendingJobs = 1000 // TODO: remove pending jobs limit
)

type cmdCreator = func(string) []string

// Runner starts and supervises running of shield simulations.
type Runner struct {
	jobsChannel        chan FileSimulationInput
	workerReleased     chan bool
	maxNumberOfWorkers int64
	workers            map[*worker]bool
	cmdCreator         func(workDir string) []string
}

// FileSimulationInput localSimulationInput.
type FileSimulationInput interface {
	Files() map[string]string
	ResultCallback(FileSimulationResults)
	StatusUpdate(model.VersionStatus)
}

// FileSimulationResults localSimulationResults.
type FileSimulationResults struct {
	Files     map[string]string
	LogStdOut string
	LogStdErr string
	Errors    map[string]string
}

// SetupRunner is RunnerSupervisor constructor.
func SetupRunner(config *conf.Config, cmdCreator cmdCreator) *Runner {
	runner := &Runner{
		jobsChannel:        make(chan FileSimulationInput, maxNumberOfPendingJobs),
		workerReleased:     make(chan bool, maxNumberOfPendingJobs),
		maxNumberOfWorkers: 2,
		workers:            map[*worker]bool{},
		cmdCreator:         cmdCreator,
	}

	for i := int64(0); i < runner.maxNumberOfWorkers; i++ {
		runner.workerReleased <- true
	}

	go runner.listenForNewJobs(config)
	return runner
}

// SubmitSimulation starts local simulation using file configured library.
func (r *Runner) SubmitSimulation(simultion FileSimulationInput) error {
	// TODO: potentialy blocking
	if len(r.jobsChannel) < maxNumberOfPendingJobs {
		log.Debug("Add pending simulation")
		r.jobsChannel <- simultion //pending}
		return nil
	}
	return fmt.Errorf("too much jobs pending")
}

func (r *Runner) listenForNewJobs(config *conf.Config) {
	for {
		<-r.workerReleased
		job := <-r.jobsChannel
		newWorker, createErr := createWorker(config, job, r.cmdCreator)
		if createErr != nil {
			continue
		}
		log.Debug("Start simulation")
		go newWorker.startWorker(r.workerReleased)
	}
}
