package simulation

import (
	"github.com/yaptide/yaptide/model"
	"github.com/yaptide/yaptide/model/action"
	"github.com/yaptide/yaptide/model/mongo"
)

type request interface {
	ConvertModel(setup *model.SimulationSetup) error
	StartSimulation() error
}

type simulationRequestContext struct {
	action *action.Resolver
	db     *mongo.DB
}
