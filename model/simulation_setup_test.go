package model

import (
	"testing"

	"github.com/davecgh/go-spew/spew"
	"github.com/stretchr/testify/require"
	"gopkg.in/mgo.v2/bson"
)

func TestSetupBsonMarshal(t *testing.T) {
	setup := InitialSimulationSetup(bson.NewObjectId())

	rawData, rawDataErr := bson.Marshal(setup)
	require.Nil(t, rawDataErr)
	actual := &SimulationSetup{}
	require.Nil(t, bson.Unmarshal(rawData, actual))

	spew.Dump(setup)
	spew.Dump(actual)
	require.Equal(t, setup, actual)
}
