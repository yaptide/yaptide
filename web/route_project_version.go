package web

import (
	"context"

	"github.com/yaptide/yaptide/model"
)

func (h *handler) createProjectVersionHandler(
	ctx context.Context,
) (*model.Project, error) {
	a := extractActionContext(ctx)
	projectID := extractProjectId(ctx)

	log.Infof("Request create new version for project %s", projectID.Hex())

	if err := h.Resolver.ProjectVersionCreateNew(a, projectID); err != nil {
		return nil, err
	}

	project, getErr := h.Resolver.ProjectGet(a, projectID)
	if getErr != nil {
		return nil, getErr
	}
	return project, nil
}

func (h *handler) createProjectVersionFromHandler(
	ctx context.Context,
) (*model.Project, error) {
	a := extractActionContext(ctx)
	projectID := extractProjectId(ctx)
	versionID := extractVersionId(ctx)

	log.Infof(
		"Request create new version from version %d for project %s",
		versionID, projectID.Hex(),
	)

	if err := h.Resolver.ProjectVersionCreateFrom(a, projectID, versionID); err != nil {
		return nil, err
	}

	project, getErr := h.Resolver.ProjectGet(a, projectID)
	if getErr != nil {
		return nil, getErr
	}
	return project, nil
}

func (h *handler) updateProjectVersionSettingsHandler(
	input *model.ProjectVersionUpdateSettings,
	ctx context.Context,
) (*model.Project, error) {
	a := extractActionContext(ctx)
	projectID := extractProjectId(ctx)
	versionID := extractVersionId(ctx)

	if err := h.Resolver.ProjectVersionUpdateSettings(a, projectID, versionID, input); err != nil {
		return nil, err
	}

	project, getErr := h.Resolver.ProjectGet(a, projectID)
	if getErr != nil {
		return nil, getErr
	}
	return project, nil
}
