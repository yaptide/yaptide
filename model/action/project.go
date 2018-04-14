package action

import (
	"github.com/yaptide/app/errors"
	"github.com/yaptide/app/model"
	"github.com/yaptide/app/model/mongo"
	"gopkg.in/mgo.v2"
	"gopkg.in/mgo.v2/bson"
)

func (r *Resolver) ProjectGetAll(
	db mongo.DB, userID bson.ObjectId,
) ([]model.Project, error) {
	projects := []model.Project{}
	getErr := db.Project().Find(bson.M{"userId": userID}).All(&projects)
	if getErr != nil {
		return nil, errors.ErrInternalServerError
	}
	return projects, nil
}

func (r *Resolver) ProjectGet(
	db mongo.DB, projectID bson.ObjectId, userID bson.ObjectId,
) (*model.Project, error) {
	project := &model.Project{}
	getErr := db.Project().FindID(projectID).One(project)
	if getErr == mgo.ErrNotFound {
		return nil, errors.ErrNotFound
	}
	if getErr != nil {
		return nil, errors.ErrInternalServerError
	}
	if project.UserID != userID {
		return nil, errors.ErrUnauthorized
	}
	return project, nil
}

func (r *Resolver) ProjectCreate(
	db mongo.DB, input *model.ProjectCreateInput, userID bson.ObjectId,
) (*model.Project, error) {
	if err := input.Validate(); err != nil {
		return nil, err
	}
	project := input.ToProject(userID)

	setup, setupErr := r.SimulationSetupCreateInitial(db, userID)
	if setupErr != nil {
		return nil, setupErr
	}
	result, resultErr := r.SimulationResultCreateInitial(db, userID)
	if resultErr != nil {
		return nil, resultErr
	}

	project.CreateInitialVersion(setup.ID, result.ID)
	insertErr := db.Project().Insert(project)
	if insertErr != nil {
		return nil, errors.ErrInternalServerError
	}

	return project, nil
}

func (r *Resolver) ProjectUpdate(
	db mongo.DB, projectID bson.ObjectId, input *model.ProjectUpdateInput, userID bson.ObjectId,
) error {
	updateErr := db.Project().Update(
		bson.M{"_id": projectID, "userId": userID},
		bson.M{"$set": input},
	)
	if updateErr == mgo.ErrNotFound {
		log.Debug("updated failed %s, reason: not found", projectID.Hex())
		return errors.ErrNotFound
	}
	if updateErr != nil {
		log.Errorf(updateErr.Error())
		return errors.ErrInternalServerError
	}

	log.Debugf("project %s updated", projectID.Hex())
	return nil
}

func (r *Resolver) ProjectRemove(
	db mongo.DB, projectID bson.ObjectId, userID bson.ObjectId,
) error {
	removeErr := db.Project().Remove(bson.M{"_id": projectID})
	if removeErr == mgo.ErrNotFound {
		return errors.ErrNotFound
	}
	if removeErr != nil {
		return errors.ErrInternalServerError
	}
	return nil
}
