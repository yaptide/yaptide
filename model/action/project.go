package action

import (
	"github.com/yaptide/yaptide/errors"
	"github.com/yaptide/yaptide/model"
	"gopkg.in/mgo.v2"
	"gopkg.in/mgo.v2/bson"
)

// ProjectGetAll ...
func (r *Resolver) ProjectGetAll(ctx *context) ([]model.Project, error) {
	projects := []model.Project{}
	getErr := ctx.db.Project().Find(bson.M{"userId": ctx.userID}).All(&projects)
	if getErr != nil {
		return nil, errors.ErrInternalServerError
	}
	return projects, nil
}

// ProjectGet ...
func (r *Resolver) ProjectGet(
	ctx *context, projectID bson.ObjectId,
) (*model.Project, error) {
	project := &model.Project{}
	getErr := ctx.db.Project().FindID(projectID).One(project)
	if getErr == mgo.ErrNotFound {
		return nil, errors.ErrNotFound
	}
	if getErr != nil {
		return nil, errors.ErrInternalServerError
	}
	if project.UserID != ctx.userID {
		return nil, errors.ErrUnauthorized
	}
	return project, nil
}

// ProjectCreate ...
func (r *Resolver) ProjectCreate(
	ctx *context, input *model.ProjectCreateInput,
) (*model.Project, error) {
	if err := input.Validate(); err != nil {
		return nil, err
	}
	project := model.NewProject(ctx.userID)
	project.Name = input.Name
	project.Description = input.Description

	setup, setupErr := r.SimulationSetupCreateInitial(ctx)
	if setupErr != nil {
		return nil, setupErr
	}
	result, resultErr := r.SimulationResultCreateInitial(ctx)
	if resultErr != nil {
		return nil, resultErr
	}
	project.Versions[0].SetupID = setup.ID
	project.Versions[0].ResultID = result.ID

	insertErr := ctx.db.Project().Insert(project)
	if insertErr != nil {
		return nil, errors.ErrInternalServerError
	}

	return project, nil
}

// ProjectUpdate ...
func (r *Resolver) ProjectUpdate(
	ctx *context, projectID bson.ObjectId, input *model.ProjectUpdateInput,
) error {
	updateErr := ctx.db.Project().Update(
		M{"_id": projectID, "userId": ctx.userID},
		M{"$set": input},
	)
	if updateErr == mgo.ErrNotFound {
		log.Warnf("project %s update failed, reason: not found", projectID.Hex())
		return errors.ErrNotFound
	}
	if updateErr != nil {
		log.Errorf(updateErr.Error())
		return errors.ErrInternalServerError
	}

	log.Debugf("project %s updated", projectID.Hex())
	return nil
}

// ProjectRemove ...
func (r *Resolver) ProjectRemove(
	ctx *context, projectID bson.ObjectId,
) error {
	removeErr := ctx.db.Project().Remove(bson.M{
		"_id":    projectID,
		"userId": ctx.userID,
	})
	if removeErr == mgo.ErrNotFound {
		return errors.ErrNotFound
	}
	if removeErr != nil {
		log.Errorf(removeErr.Error())
		return errors.ErrInternalServerError
	}
	return nil
}
