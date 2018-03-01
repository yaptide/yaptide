package model

import (
	"github.com/yaptide/converter/setup"
	"gopkg.in/mgo.v2/bson"
)

type SimulationSetup struct {
	ID          bson.ObjectId `json:"id" bson:"_id"`
	UserID      bson.ObjectId `json:"userId" bson: "userID"`
	setup.Setup `bson:",inline"`
}

func InitialSimulationSetup(userID bson.ObjectId) *SimulationSetup {
	return &SimulationSetup{
		ID:     bson.NewObjectId(),
		UserID: userID,
		Setup:  setup.NewEmptySetup(),
	}
}
