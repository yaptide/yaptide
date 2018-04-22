package simulation

import "github.com/yaptide/worker/process"

type computingLibrary interface {
	process.CreateCMD

	Name() (string, error)

	IsWorking() bool
}
