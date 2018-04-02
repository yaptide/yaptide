package action

import (
	"github.com/yaptide/app/errors"
	"github.com/yaptide/app/model"
	"github.com/yaptide/app/model/mongo"
	"github.com/yaptide/converter"
	"gopkg.in/mgo.v2"
	"gopkg.in/mgo.v2/bson"
)

func (r *Resolver) SimulationSetupGet(
	db mongo.DB, setupID bson.ObjectId, userID bson.ObjectId,
) (*model.SimulationSetup, error) {
	setup := &model.SimulationSetup{}
	getErr := db.SimulationSetup().FindID(setupID).One(setup)
	if getErr != mgo.ErrNotFound {
		return nil, errors.ErrNotFound
	}
	if getErr != nil {
		return nil, errors.ErrInternalServerError
	}
	if setup.UserID != userID {
		return nil, errors.ErrUnauthorized
	}
	return setup, nil
}

func (r *Resolver) SimulationSetupCreateInitial(
	db mongo.DB, userID bson.ObjectId,
) (*model.SimulationSetup, error) {
	setup := model.InitialSimulationSetup(userID)
	insertErr := db.SimulationSetup().Insert(setup)
	if insertErr != nil {
		return nil, errors.ErrInternalServerError
	}
	return setup, nil
}

func (r *Resolver) SimulationSetupCreateFrom(
	db mongo.DB, setupID bson.ObjectId, userID bson.ObjectId,
) (*model.SimulationSetup, error) {
	setup, getErr := r.SimulationSetupGet(db, setupID, userID)
	if getErr != nil {
		return nil, getErr
	}
	setup.ID = bson.NewObjectId()
	insertErr := db.SimulationSetup().Insert(setup)
	if insertErr != nil {
		return nil, errors.ErrInternalServerError
	}
	return setup, nil
}

func (r *Resolver) SimulationSetupUpdate(
	db mongo.DB, setup *model.SimulationSetup, input *converter.Setup,
) (*model.SimulationSetup, error) {
	setup.Setup = *input
	updateErr := db.SimulationSetup().UpdateID(setup.ID, setup)
	if updateErr != nil {
		return nil, errors.ErrInternalServerError
	}
	return setup, nil
}
