package simulation

import (
	"github.com/yaptide/yaptide/model"
)

type request interface {
	ConvertModel(setup *model.SimulationSetup) error
	StartSimulation() error
}
