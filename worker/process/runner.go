// Package process implements mechanism of starting and supervising simulation processes.
package process

import (
	"os/exec"
)

const (
	maxNumberOfWorkers = 10
)

// CreateCMD create command which run simulation process.
type CreateCMD interface {
	CreateCMD(workingDirPath string) *exec.Cmd
}

// Runner starts and supervises running of simulations.
type Runner struct {
	workerTokens chan bool
}

// Result of simulation run.
type Result struct {
	Files  map[string]string
	StdOut string
	StdErr string
	Errors []string
}

// NewRunner create Runner which is ready to run new jobs.
func NewRunner() Runner {
	runner := Runner{
		workerTokens: make(chan bool, maxNumberOfWorkers),
	}

	for i := 0; i < maxNumberOfWorkers; i++ {
		runner.workerTokens <- true
	}

	return runner
}

// Run new job.
func (r *Runner) Run(createCMD CreateCMD, inputFiles map[string]string) Result {
	select {
	case <-r.workerTokens:
		defer func() { r.workerTokens <- true }()
		return runProcess(createCMD, inputFiles, maxJobDuration)

	default:
		return Result{
			Errors: []string{
				"to much jobs pending",
			},
		}
	}
}
