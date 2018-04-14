package web

import (
	"context"

	"github.com/yaptide/app/model"
)

func (h *handler) getProjectsHandler(ctx context.Context) ([]model.Project, error) {
	db := extractDBSession(ctx)
	userID := extractUserId(ctx)

	log.Debugf("Request get all projects for user %s", userID.Hex())

	projects, projectErr := h.Resolver.ProjectGetAll(db, userID)

	return projects, projectErr
}

func (h *handler) getProjectHandler(ctx context.Context) (*model.Project, error) {
	db := extractDBSession(ctx)
	userID := extractUserId(ctx)
	projectID := extractProjectId(ctx)

	log.Debugf("Request get project %s", projectID.Hex())

	return h.Resolver.ProjectGet(db, projectID, userID)
}

func (h *handler) createProjectHandler(
	input *model.ProjectCreateInput, ctx context.Context,
) (*model.Project, error) {
	db := extractDBSession(ctx)
	userID := extractUserId(ctx)

	log.Infof("Request create project")

	project, projectErr := h.Resolver.ProjectCreate(db, input, userID)

	return project, projectErr
}

func (h *handler) updateProjectHandler(
	input *model.ProjectUpdateInput, ctx context.Context,
) (*model.Project, error) {
	db := extractDBSession(ctx)
	userID := extractUserId(ctx)
	projectID := extractProjectId(ctx)

	log.Infof("Request update project %s", projectID.Hex())

	if err := h.Resolver.ProjectUpdate(db, projectID, input, userID); err != nil {
		return nil, err
	}

	project, getErr := h.Resolver.ProjectGet(db, projectID, userID)
	if getErr != nil {
		return nil, getErr
	}
	return project, nil
}

func (h *handler) removeProjectHandler(
	ctx context.Context,
) (bool, error) {
	db := extractDBSession(ctx)
	userID := extractUserId(ctx)
	projectID := extractProjectId(ctx)

	log.Debugf("Request delete project %s", projectID.Hex())

	projectErr := h.Resolver.ProjectRemove(db, projectID, userID)

	return true, projectErr
}
