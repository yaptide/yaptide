package simulation

import (
	"github.com/yaptide/app/model"
	"github.com/yaptide/app/runner/file"
	"github.com/yaptide/converter/result"
	"github.com/yaptide/converter/shield"
	"github.com/yaptide/converter/shield/results"
	"github.com/yaptide/converter/shield/setup"
)

type shieldProcessor struct {
	*setup.RawShieldSetup
	serializationContext *shield.SerializationContext
}

func (r *shieldProcessor) ConvertModel(simSetup *model.SimulationSetup) error {
	convertedModel, serializationContext, convertErr := setup.Convert(simSetup.Setup)
	if convertErr != nil {
		return convertErr
	}
	r.RawShieldSetup = convertedModel
	r.serializationContext = serializationContext
	return nil
}

func (p *shieldProcessor) HandleFileResults(
	simResults file.FileSimulationResults,
) (*result.Result, error) {
	parserOutput, parserErr := results.ParseResults(
		simResults.Files,
		p.serializationContext,
	)
	if parserErr != nil {
		return nil, parserErr
	}
	return parserOutput, nil
}
