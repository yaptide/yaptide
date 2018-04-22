package model

import (
	"github.com/yaptide/yaptide/pkg/converter"
	"gopkg.in/mgo.v2/bson"
)

// SimulationResult ...
type SimulationResult struct {
	ID               bson.ObjectId `json:"id" bson:"_id"`
	UserID           bson.ObjectId `json:"userId" bson:"userId"`
	converter.Result `bson:",inline"`
}

// InitialSimulationResult ...
func InitialSimulationResult(userID bson.ObjectId) *SimulationResult {
	return &SimulationResult{
		ID:     bson.NewObjectId(),
		UserID: userID,
		Result: converter.NewEmptyResult(),
	}
}
