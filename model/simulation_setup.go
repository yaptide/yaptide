package model

import (
	"github.com/yaptide/converter"
	"gopkg.in/mgo.v2/bson"
)

type SimulationSetup struct {
	ID              bson.ObjectId `json:"id" bson:"_id"`
	UserID          bson.ObjectId `json:"userId" bson: "userID"`
	converter.Setup `bson:",inline"`
}

func InitialSimulationSetup(userID bson.ObjectId) *SimulationSetup {
	return &SimulationSetup{
		ID:     bson.NewObjectId(),
		UserID: userID,
		Setup:  converter.NewEmptySetup(),
	}
}
