package simulation

import (
	"github.com/yaptide/app/model"
	"github.com/yaptide/app/model/action"
	"github.com/yaptide/app/model/mongo"
)

type request interface {
	ConvertModel(setup *model.SimulationSetup) error
	StartSimulation() error
}

type simulationRequestContext struct {
	action *action.Resolver
	db     *mongo.DB
}
