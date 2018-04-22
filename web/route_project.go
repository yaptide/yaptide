package web

import (
	"context"

	"github.com/yaptide/yaptide/model"
)

func (h *handler) getProjectsHandler(ctx context.Context) ([]model.Project, error) {
	a := extractActionContext(ctx)

	log.Debugf("Request get all projects for user %s", a.UserID().Hex())

	projects, projectErr := h.Resolver.ProjectGetAll(a)

	return projects, projectErr
}

func (h *handler) getProjectHandler(ctx context.Context) (*model.Project, error) {
	a := extractActionContext(ctx)
	projectID := extractProjectID(ctx)

	log.Debugf("Request get project %s for user %s", projectID.Hex(), a.UserID().Hex())

	return h.Resolver.ProjectGet(a, projectID)
}

func (h *handler) createProjectHandler(
	ctx context.Context, input *model.ProjectCreateInput,
) (*model.Project, error) {
	a := extractActionContext(ctx)

	log.Infof("Request create project for user %s", a.UserID().Hex())

	project, projectErr := h.Resolver.ProjectCreate(a, input)

	return project, projectErr
}

func (h *handler) updateProjectHandler(
	ctx context.Context, input *model.ProjectUpdateInput,
) (*model.Project, error) {
	a := extractActionContext(ctx)
	projectID := extractProjectID(ctx)

	log.Infof("Request update project %s for user %s", projectID.Hex(), a.UserID().Hex())

	if err := h.Resolver.ProjectUpdate(a, projectID, input); err != nil {
		return nil, err
	}

	project, getErr := h.Resolver.ProjectGet(a, projectID)
	if getErr != nil {
		return nil, getErr
	}
	return project, nil
}

func (h *handler) removeProjectHandler(
	ctx context.Context,
) (bool, error) {
	a := extractActionContext(ctx)
	projectID := extractProjectID(ctx)

	log.Infof("Request delete project %s", projectID.Hex())

	projectErr := h.Resolver.ProjectRemove(a, projectID)

	return true, projectErr
}
