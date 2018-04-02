package simulation

import (
	"github.com/yaptide/app/model"
	"github.com/yaptide/app/runner/file"
	"github.com/yaptide/converter"
	"github.com/yaptide/converter/shield"
)

type shieldProcessor struct {
	shield.RawShieldSetup
	serializationContext shield.SerializationContext
}

func (r *shieldProcessor) ConvertModel(simSetup *model.SimulationSetup) error {
	convertedModel, serializationContext, convertErr := shield.Convert(simSetup.Setup)
	if convertErr != nil {
		return convertErr
	}
	r.RawShieldSetup = convertedModel
	r.serializationContext = serializationContext
	return nil
}

func (p *shieldProcessor) HandleFileResults(
	simResults file.FileSimulationResults,
) (*converter.Result, error) {
	parserOutput, parserErr := shield.ParseResults(
		simResults.Files,
		&p.serializationContext,
	)
	if parserErr != nil {
		return nil, parserErr
	}
	return parserOutput, nil
}
