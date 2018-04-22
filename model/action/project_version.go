package action

import (
	"fmt"
	"time"

	"github.com/yaptide/yaptide/errors"
	"github.com/yaptide/yaptide/model"
	"gopkg.in/mgo.v2/bson"
)

func (r *Resolver) ProjectVersionCreateNew(
	ctx *context, projectID bson.ObjectId,
) error {
	project, getErr := r.ProjectGet(ctx, projectID)
	if getErr != nil {
		return getErr
	}
	versionErr := r.projectVersionCreateFromExisting(
		ctx, projectID, len(project.Versions)-1,
	)
	if versionErr != nil {
		return versionErr
	}

	return nil
}

func (r *Resolver) ProjectVersionCreateFrom(
	ctx *context, projectID bson.ObjectId, versionID int,
) error {
	versionErr := r.projectVersionCreateFromExisting(
		ctx, projectID, versionID,
	)
	if versionErr != nil {
		return versionErr
	}
	return nil
}
func (r *Resolver) projectVersionCreateFromExisting(
	ctx *context, projectID bson.ObjectId, versionID int,
) error {
	log.Debugf("Create version from %d version", versionID)
	project, getErr := r.ProjectGet(ctx, projectID)
	if getErr != nil {
		return getErr
	}
	if len(project.Versions) <= versionID {
		return errors.ErrNotFound
	}

	oldVersion := &project.Versions[versionID]

	setup, setupErr := r.SimulationSetupCreateFrom(ctx, oldVersion.SetupID)
	if setupErr != nil {
		log.Warnf(
			"SimulationSetup create failed for project %s version %d",
			projectID.Hex(), versionID,
		)
		return setupErr
	}
	result, resultErr := r.SimulationResultCreateInitial(ctx)
	if resultErr != nil {
		log.Warnf(
			"SimulationResult create failed for project %s version %d",
			projectID.Hex(), versionID,
		)
		return resultErr
	}

	version := model.Version{
		ID:        len(project.Versions),
		Settings:  oldVersion.Settings,
		Status:    model.New,
		SetupID:   setup.ID,
		ResultID:  result.ID,
		UpdatedAt: time.Now(),
	}

	update := M{
		"$push": M{
			"versions": version,
		},
	}

	updateErr := ctx.db.Project().Update(M{
		"_id":    project.ID,
		"userId": ctx.userID,
	}, update)
	if updateErr != nil {
		return errors.ErrInternalServerError
	}
	return nil
}

func (r *Resolver) ProjectVersionUpdateSettings(
	ctx *context, projectID bson.ObjectId, versionID int,
	input *model.ProjectVersionUpdateSettings,
) error {

	updateErr := ctx.db.Project().Update(M{
		"_id":    projectID,
		"userId": ctx.userID,
		fmt.Sprintf("versions.%d", versionID): M{"$exists": true},
	}, M{
		"$set": M{
			fmt.Sprintf("versions.%d.settings", versionID): input,
			fmt.Sprintf("versions.%d.status", versionID):   model.Edited,
		},
	})
	if updateErr != nil {
		return updateErr
	}

	return nil
}

func (r *Resolver) EnsureLastProjectVersionStatus(
	ctx *context, projectID bson.ObjectId,
) error {
	project, projectErr := r.ProjectGet(ctx, projectID)
	if projectErr != nil {
		return projectErr
	}
	lastVersionStatus := project.Versions[len(project.Versions)].Status

	if lastVersionStatus.IsFinal() {
		createErr := r.ProjectVersionCreateNew(ctx, projectID)
		if createErr != nil {
			return errors.ErrInternalServerError
		}
	}
	return nil
}
