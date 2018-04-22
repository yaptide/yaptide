package simulation

import "github.com/yaptide/yaptide/worker/process"

type computingLibrary interface {
	process.CreateCMD

	Name() (string, error)

	IsWorking() bool
}
