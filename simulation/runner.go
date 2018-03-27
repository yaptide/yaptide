package simulation

import (
	"errors"

	"github.com/yaptide/worker/process"
)

var ErrComputingLibrariesNotFound = errors.New("computing libraries not found")

var supportedComputingLibraries = []computingLibrary{shieldHIT12A{}}

type Runner struct {
	processRunner      process.Runner
	computingLibraries []computingLibrary
}

func NewRunner(processRunner process.Runner) (Runner, error) {
	runner := Runner{
		processRunner:      processRunner,
		computingLibraries: []computingLibrary{},
	}

	for _, computingLib := range supportedComputingLibraries {
		if computingLib.IsWorking() {
			runner.computingLibraries = append(runner.computingLibraries, computingLib)
		}
	}

	if len(runner.computingLibraries) == 0 {
		return Runner{}, ErrComputingLibrariesNotFound
	}
	return runner, nil
}

func (r *Runner) AvailableComputingLibrariesNames() []string {
	names := []string{}
	for _, computingLibrary := range r.computingLibraries {
		names = append(names, computingLibrary.Name())
	}
	return names
}

func (r *Runner) Run(name string, inputFiles map[string]string) (resultFiles, errors map[string]string) {
	resultFiles, errors = map[string]string{}, map[string]string{}
	return
}
