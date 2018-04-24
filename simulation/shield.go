package simulation

import (
	"github.com/yaptide/yaptide/model"
	"github.com/yaptide/yaptide/pkg/converter"
	"github.com/yaptide/yaptide/pkg/converter/shield"
	"github.com/yaptide/yaptide/runner/file"
)

type shieldProcessor struct {
	shield.RawShieldSetup
	serializationContext shield.SerializationContext
}

func (p *shieldProcessor) ConvertModel(simSetup *model.SimulationSetup) error {
	convertedModel, serializationContext, convertErr := shield.Convert(simSetup.Setup)
	if convertErr != nil {
		return convertErr
	}
	p.RawShieldSetup = convertedModel
	p.serializationContext = serializationContext
	return nil
}

func (p *shieldProcessor) HandleFileResults(
	simResults file.SimulationResults,
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
