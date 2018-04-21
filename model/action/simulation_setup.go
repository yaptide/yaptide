package action

import (
	"github.com/yaptide/app/errors"
	"github.com/yaptide/app/model"
	"github.com/yaptide/converter"
	"gopkg.in/mgo.v2"
	"gopkg.in/mgo.v2/bson"
)

func (r *Resolver) SimulationSetupGet(
	ctx *context, setupID bson.ObjectId,
) (*model.SimulationSetup, error) {
	setup := model.SimulationSetup{}
	log.Error(setupID, ctx.userID)
	getErr := ctx.db.SimulationSetup().Find(bson.M{
		"_id":    setupID,
		"userId": ctx.userID,
	}).One(&setup)
	if getErr == mgo.ErrNotFound {
		log.Warn(getErr.Error())
		return nil, errors.ErrNotFound
	}
	if getErr != nil {
		log.Warn(getErr.Error())
		return nil, errors.ErrInternalServerError
	}
	if setup.UserID != ctx.userID {
		return nil, errors.ErrUnauthorized
	}
	return &setup, nil
}

// SimulationSetupCreateInitial creates default starting simulation and
// inserts it into db.
func (r *Resolver) SimulationSetupCreateInitial(
	ctx *context,
) (*model.SimulationSetup, error) {
	setup := model.InitialSimulationSetup(ctx.userID)
	insertErr := ctx.db.SimulationSetup().Insert(setup)
	if insertErr != nil {
		log.Warnf(
			"SimulationSetup initial insert failed for setup %s with error[%s]",
			setup.ID.Hex(), insertErr.Error(),
		)
		return nil, errors.ErrInternalServerError
	}
	return setup, nil
}

// SimulationSetupCreateFrom creates copy of simulation setup selected by id
// and inserts it into db.
func (r *Resolver) SimulationSetupCreateFrom(
	ctx *context, setupID bson.ObjectId,
) (*model.SimulationSetup, error) {
	setup, getErr := r.SimulationSetupGet(ctx, setupID)
	if getErr != nil {
		log.Warnf(
			"SimulationSetup get failed for setup %s",
			setupID.Hex(),
		)
		return nil, getErr
	}
	setup.ID = bson.NewObjectId()
	setup.UserID = ctx.userID
	insertErr := ctx.db.SimulationSetup().Insert(setup)
	if insertErr != nil {
		log.Warnf(
			"SimulationSetup insert failed for setup %s with error[%s]",
			setupID.Hex(), insertErr.Error(),
		)
		return nil, errors.ErrInternalServerError
	}
	return setup, nil
}

// SimulationSetupUpdate relaces entire setup object inside db.
func (r *Resolver) SimulationSetupUpdate(
	ctx *context, setupID bson.ObjectId, input *converter.Setup,
) error {
	updateErr := ctx.db.SimulationSetup().Update(M{
		"_id":    setupID,
		"userId": ctx.userID,
	}, M{
		"$set": input,
	})
	if updateErr != nil {
		return errors.ErrInternalServerError
	}
	return nil
}
