package web

import (
	"context"

	"github.com/yaptide/app/model"
)

func (h *handler) getProjectsHandler(ctx context.Context) ([]model.Project, error) {
	db := extractDBSession(ctx)
	userID := extractUserId(ctx)

	projects, projectErr := h.Resolver.ProjectGetAll(db, userID)

	return projects, projectErr
}

func (h *handler) getProjectHandler(ctx context.Context) (*model.Project, error) {
	db := extractDBSession(ctx)
	userID := extractUserId(ctx)
	projectID := extractProjectId(ctx)

	project, projectErr := h.Resolver.ProjectGet(db, projectID, userID)

	return project, projectErr
}

func (h *handler) createProjectHandler(
	input *model.ProjectCreateInput, ctx context.Context,
) (*model.Project, error) {
	db := extractDBSession(ctx)
	userID := extractUserId(ctx)

	project, projectErr := h.Resolver.ProjectCreate(db, input, userID)

	return project, projectErr
}

func (h *handler) updateProjectHandler(
	input *model.ProjectUpdateInput, ctx context.Context,
) (*model.Project, error) {
	db := extractDBSession(ctx)
	userID := extractUserId(ctx)
	projectID := extractProjectId(ctx)

	project, getErr := h.Resolver.ProjectGet(db, projectID, userID)
	if getErr != nil {
		return nil, getErr
	}

	project, projectErr := h.Resolver.ProjectUpdate(db, project, input)

	return project, projectErr
}

func (h *handler) removeProjectHandler(
	ctx context.Context,
) (bool, error) {
	db := extractDBSession(ctx)
	userID := extractUserId(ctx)
	projectID := extractProjectId(ctx)

	projectErr := h.Resolver.ProjectRemove(db, projectID, userID)

	return true, projectErr
}
