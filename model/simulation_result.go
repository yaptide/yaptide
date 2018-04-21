package model

import (
	"github.com/yaptide/converter"
	"gopkg.in/mgo.v2/bson"
)

type SimulationResult struct {
	ID               bson.ObjectId `json:"id" bson:"_id"`
	UserID           bson.ObjectId `json:"userId" bson:"userId"`
	converter.Result `bson:",inline"`
}

func InitialSimulationResult(userID bson.ObjectId) *SimulationResult {
	return &SimulationResult{
		ID:     bson.NewObjectId(),
		UserID: userID,
		Result: converter.NewEmptyResult(),
	}
}
