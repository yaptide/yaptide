package model

import (
	"github.com/yaptide/converter/result"
	"gopkg.in/mgo.v2/bson"
)

type SimulationResult struct {
	ID            bson.ObjectId `json:"id" bson:"_id"`
	UserID        bson.ObjectId `json:"userId" bson: "userID"`
	result.Result `bson:",inline"`
}

func InitialSimulationResult(userID bson.ObjectId) *SimulationResult {
	return &SimulationResult{
		ID:     bson.NewObjectId(),
		UserID: userID,
		Result: result.NewEmptyResult(),
	}
}
