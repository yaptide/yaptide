package web

import (
	"context"

	"github.com/yaptide/app/model"
)

func (h *handler) createProjectVersionHandler(
	ctx context.Context,
) (*model.Version, error) {
	db := extractDBSession(ctx)
	userID := extractUserId(ctx)
	projectID := extractProjectId(ctx)

	project, getErr := h.Resolver.ProjectGet(db, projectID, userID)
	if getErr != nil {
		return nil, getErr
	}

	version, createErr := h.Resolver.ProjectVersionCreateNew(db, project)
	return version, createErr
}

func (h *handler) createProjectVersionFromHandler(
	ctx context.Context,
) (*model.Version, error) {
	db := extractDBSession(ctx)
	userID := extractUserId(ctx)
	projectID := extractProjectId(ctx)
	versionID := extractVersionId(ctx)

	project, getErr := h.Resolver.ProjectGet(db, projectID, userID)
	if getErr != nil {
		return nil, getErr
	}

	version, createErr := h.Resolver.ProjectVersionCreateFrom(db, project, versionID)
	return version, createErr
}

func (h *handler) updateProjectVersionHandler(
	input *model.ProjectVersionUpdateInput,
	ctx context.Context,
) (*model.Version, error) {
	db := extractDBSession(ctx)
	userID := extractUserId(ctx)
	projectID := extractProjectId(ctx)
	versionID := extractVersionId(ctx)

	project, getErr := h.Resolver.ProjectGet(db, projectID, userID)
	if getErr != nil {
		return nil, getErr
	}
	version, createErr := h.Resolver.ProjectVersionUpdate(db, project, versionID, input)
	return version, createErr
}
