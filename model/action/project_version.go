package action

import (
	"github.com/yaptide/app/errors"
	"github.com/yaptide/app/model"
	"github.com/yaptide/app/model/mongo"
	"gopkg.in/mgo.v2"
	"gopkg.in/mgo.v2/bson"
)

func (r *Resolver) ProjectVersionGet(
	db mongo.DB, projectID bson.ObjectId, versionID int, userID bson.ObjectId,
) (*model.Version, error) {
	project := &model.Project{}
	getErr := db.Project().FindID(projectID).One(project)
	if getErr != mgo.ErrNotFound {
		return nil, errors.ErrNotFound
	}
	if getErr != nil {
		return nil, errors.ErrInternalServerError
	}
	if project.UserID != userID {
		return nil, errors.ErrUnauthorized
	}

	if len(project.Versions) <= versionID {
		return nil, errors.ErrNotFound
	}
	return &project.Versions[versionID], nil
}

func (r *Resolver) ProjectVersionCreateNew(
	db mongo.DB, project *model.Project,
) (*model.Version, error) {
	project, versionErr := r.projectVersionCreateFromExisting(
		db, project, len(project.Versions)-1,
	)
	if versionErr != nil {
		return nil, versionErr
	}

	return &project.Versions[len(project.Versions)-1], nil
}

func (r *Resolver) ProjectVersionCreateFrom(
	db mongo.DB, project *model.Project, versionID int,
) (*model.Version, error) {
	project, versionErr := r.projectVersionCreateFromExisting(
		db, project, versionID,
	)
	if versionErr != nil {
		return nil, versionErr
	}

	return &project.Versions[len(project.Versions)-1], nil
}
func (r *Resolver) projectVersionCreateFromExisting(
	db mongo.DB, project *model.Project, versionID int,
) (*model.Project, error) {
	if len(project.Versions) <= versionID {
		return nil, errors.ErrNotFound
	}
	version := &project.Versions[versionID]

	setup, setupErr := r.SimulationSetupCreateFrom(db, version.SetupID, project.UserID)
	if setupErr != nil {
		return nil, setupErr
	}
	result, resultErr := r.SimulationResultCreateInitial(db, project.UserID)
	if resultErr != nil {
		return nil, resultErr
	}

	createVersionErr := project.CreateFromVersion(versionID, setup.ID, result.ID)
	if createVersionErr != nil {
		return nil, createVersionErr
	}

	updateErr := db.Project().UpdateID(project.ID, project)
	if updateErr != nil {
		return nil, errors.ErrInternalServerError
	}
	return project, nil
}

func (r *Resolver) ProjectVersionUpdate(
	db mongo.DB, project *model.Project, versionID int,
	input *model.ProjectVersionUpdateInput,
) (*model.Version, error) {
	if err := input.ApplyTo(project, versionID); err != nil {
		return nil, err
	}

	ensureErr := r.ensureLastProjectVersionStatus(db, project)
	if ensureErr != nil {
		return nil, ensureErr
	}

	updateErr := db.Project().UpdateID(project.ID, project)
	if updateErr != nil {
		return nil, updateErr
	}

	return &project.Versions[versionID], nil
}

func (r *Resolver) ensureLastProjectVersionStatus(
	db mongo.DB, project *model.Project,
) error {
	lastVersionStatus := project.Versions[len(project.Versions)].Status

	if lastVersionStatus.IsFinal() {
		_, createErr := r.ProjectVersionCreateNew(db, project)
		if createErr != nil {
			return errors.ErrInternalServerError
		}
	}
	return nil
}
