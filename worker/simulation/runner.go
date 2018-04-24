// Package simulation runs simulation based on received requests.
package simulation

import (
	"errors"
	"sort"

	"github.com/yaptide/yaptide/worker/process"
)

// ErrComputingLibrariesNotFound error.
var ErrComputingLibrariesNotFound = errors.New("Computing libraries not found")

var supportedComputingLibraries = []computingLibrary{shieldHIT12A{}}

// Runner run simulations.
type Runner struct {
	processRunner      process.Runner
	computingLibraries map[string]computingLibrary
}

// NewRunner constructor.
func NewRunner(processRunner process.Runner) (Runner, error) {
	runner := Runner{
		processRunner:      processRunner,
		computingLibraries: map[string]computingLibrary{},
	}

	for _, computingLib := range supportedComputingLibraries {
		if computingLib.IsWorking() {
			name, err := computingLib.Name()
			if err != nil {
				return Runner{}, err
			}
			runner.computingLibraries[name] = computingLib
		}
	}

	if len(runner.computingLibraries) == 0 {
		return Runner{}, ErrComputingLibrariesNotFound
	}
	return runner, nil
}

// AvailableComputingLibrariesNames return list of availables computing
// libraries names.
func (r *Runner) AvailableComputingLibrariesNames() []string {
	names := []string{}
	for name := range r.computingLibraries {
		names = append(names, name)
	}

	sort.Strings(names)
	return names
}

// Run simulation.
// Return error, if computingLibrary is not registered.
func (r *Runner) Run(
	computingLibraryName string, inputFiles map[string]string,
) (resultFiles map[string]string, errors []string) {
	computingLibrary, found := r.computingLibraries[computingLibraryName]
	if !found {
		return resultFiles, []string{"computing library not found/available"}
	}

	result := r.processRunner.Run(computingLibrary, inputFiles)

	return result.Files, result.Errors
}
