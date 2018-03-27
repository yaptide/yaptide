// Package runner implements mechanism of starting and supervising simulations.
// Simulations are started by running binary configured using config files.
package process

import (
	"fmt"
	"os/exec"
)

const (
	maxNumberOfWorkers = 10
)

type CreateCDMFuncGenerator interface {
	CreateCMDFunc(workingDirPath string) *exec.Cmd
}

// Runner starts and supervises running of shield simulations.
type Runner struct {
	jobsQueue    chan inputResultsChanPair
	workerTokens chan bool
}

type Input struct {
	Files                  map[string]string
	CreateCDMFuncGenerator CreateCDMFuncGenerator
}

type Result struct {
	Files  map[string]string
	StdOut string
	StdErr string
	Errors map[string]string
}

// CreateRunner create new runner, which start listening for new jobs.
func CreateRunner() Runner {
	runner := Runner{
		workerTokens: make(chan bool, maxNumberOfWorkers),
	}

	for i := 0; i < maxNumberOfWorkers; i++ {
		runner.workerTokens <- true
	}

	return runner
}

// Start .
func (r *Runner) Start(cmd CreateCDMFuncGenerator, inputFiles map[string]string) (Result, error) {
	resultChan := make(chan Result)
	select {
	case r.jobsQueue <- inputResultsChanPair{input, resultChan}:
	default:
		return nil, fmt.Errorf("too much jobs pending")
	}

	return <-resultChan
}
