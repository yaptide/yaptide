package simulation

import (
	"github.com/yaptide/yaptide/model"
	"github.com/yaptide/yaptide/model/action"
	"github.com/yaptide/yaptide/pkg/converter"
	"github.com/yaptide/yaptide/runner/file"
)

type fileProcessor interface {
	ConvertModel(setup *model.SimulationSetup) error
	Files() map[string]string
	HandleFileResults(file.SimulationResults) (*converter.Result, error)
}

type fileRequest struct {
	*file.Runner
	fileProcessor
	*action.SimulationContext
}

func (fr *fileRequest) StartSimulation() error {
	simulationErr := fr.Runner.SubmitSimulation(fr)
	if simulationErr != nil {
		log.Warning("[Processor][localfile][Simulation] failed to schedule job")
		return simulationErr
	}
	return nil
}

func (fr *fileRequest) ResultCallback(simResults file.SimulationResults) {
	results, parseErr := fr.HandleFileResults(simResults)
	if parseErr != nil {
		fr.SimulationContext.StatusUpdate(model.Failure)
	} else {
		fr.SimulationContext.StatusUpdate(model.Success)
	}
	if err := fr.SimulationContext.SetProjectResults(results, parseErr); err != nil {
		log.Error("unable to save simulation results")
		return
	}
}
