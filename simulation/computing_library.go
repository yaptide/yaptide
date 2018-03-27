package simulation

import "github.com/yaptide/worker/process"

type computingLibrary interface {
	process.CreateCDMFuncGenerator

	Name() string

	IsWorking() bool
}
