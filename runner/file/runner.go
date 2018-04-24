// Package file implements mechanism of starting and supervising simulations.
// Simulations are started by running binary configured using config files.
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
	jobsChannel        chan SimulationInput
	workerReleased     chan bool
	maxNumberOfWorkers int64
	workers            map[*worker]bool
	cmdCreator         func(workDir string) []string
}

// SimulationInput localSimulationInput.
type SimulationInput interface {
	Files() map[string]string
	ResultCallback(SimulationResults)
	StatusUpdate(model.VersionStatus)
}

// SimulationResults localSimulationResults.
type SimulationResults struct {
	Files     map[string]string
	LogStdOut string
	LogStdErr string
	Errors    map[string]string
}

// SetupRunner is RunnerSupervisor constructor.
func SetupRunner(config *conf.Config, cmdCreator cmdCreator) *Runner {
	runner := &Runner{
		jobsChannel:        make(chan SimulationInput, maxNumberOfPendingJobs),
		workerReleased:     make(chan bool, maxNumberOfPendingJobs),
		maxNumberOfWorkers: 2,
		workers:            map[*worker]bool{},
		cmdCreator:         cmdCreator,
	}

	for i := int64(0); i < runner.maxNumberOfWorkers; i++ {
		runner.workerReleased <- true
	}

	go runner.listenForNewJobs()
	return runner
}

// SubmitSimulation starts local simulation using file configured library.
func (r *Runner) SubmitSimulation(simultion SimulationInput) error {
	// TODO: potentially blocking
	if len(r.jobsChannel) < maxNumberOfPendingJobs {
		log.Debug("Add pending simulation")
		r.jobsChannel <- simultion //pending}
		return nil
	}
	return fmt.Errorf("too much jobs pending")
}

func (r *Runner) listenForNewJobs() {
	for {
		<-r.workerReleased
		job := <-r.jobsChannel
		newWorker, createErr := createWorker(job, r.cmdCreator)
		if createErr != nil {
			continue
		}
		log.Debug("Start simulation")
		go newWorker.startWorker(r.workerReleased)
	}
}
