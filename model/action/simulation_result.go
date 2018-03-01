package action

import (
	"github.com/yaptide/app/errors"
	"github.com/yaptide/app/model"
	"github.com/yaptide/app/model/mongo"
	"gopkg.in/mgo.v2"
	"gopkg.in/mgo.v2/bson"
)

func (r *Resolver) SimulationResultGet(
	db mongo.DB, resultID bson.ObjectId, userID bson.ObjectId,
) (*model.SimulationResult, error) {
	result := &model.SimulationResult{}
	getErr := db.SimulationResult().FindID(resultID).One(result)
	if getErr != mgo.ErrNotFound {
		return nil, errors.ErrNotFound
	}
	if getErr != nil {
		return nil, errors.ErrInternalServerError
	}
	if result.UserID != userID {
		return nil, errors.ErrUnauthorized
	}
	return result, nil
}

func (r *Resolver) SimulationResultCreateInitial(
	db mongo.DB, userID bson.ObjectId,
) (*model.SimulationResult, error) {
	result := model.InitialSimulationResult(userID)
	insertErr := db.SimulationResult().Insert(result)
	if insertErr != nil {
		return nil, errors.ErrInternalServerError
	}
	return result, nil
}
