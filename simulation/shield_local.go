package simulation

import (
	"github.com/yaptide/app/model"
	"github.com/yaptide/app/model/action"
	"github.com/yaptide/app/runner/file"
	"github.com/yaptide/converter/result"
)

type fileProcessor interface {
	ConvertModel(setup *model.SimulationSetup) error
	Files() map[string]string
	HandleFileResults(file.FileSimulationResults) (*result.Result, error)
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

func (fr *fileRequest) ResultCallback(simResults file.FileSimulationResults) {
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
