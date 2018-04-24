package action

import (
	"github.com/yaptide/yaptide/errors"
	"github.com/yaptide/yaptide/model"
	"gopkg.in/mgo.v2"
	"gopkg.in/mgo.v2/bson"
)

// SimulationResultGet ...
func (r *Resolver) SimulationResultGet(
	ctx *context, resultID bson.ObjectId,
) (*model.SimulationResult, error) {
	result := &model.SimulationResult{}
	getErr := ctx.db.SimulationResult().Find(M{
		"_id":    resultID,
		"userId": ctx.userID,
	}).One(result)
	if getErr == mgo.ErrNotFound {
		return nil, errors.ErrNotFound
	}
	if getErr != nil {
		return nil, errors.ErrInternalServerError
	}
	if result.UserID != ctx.userID {
		return nil, errors.ErrUnauthorized
	}
	return result, nil
}

// SimulationResultCreateInitial ...
func (r *Resolver) SimulationResultCreateInitial(
	ctx *context,
) (*model.SimulationResult, error) {
	result := model.InitialSimulationResult(ctx.userID)
	insertErr := ctx.db.SimulationResult().Insert(result)
	if insertErr != nil {
		return nil, errors.ErrInternalServerError
	}
	return result, nil
}
