package web

import (
	"context"

	"github.com/yaptide/yaptide/model"
	"github.com/yaptide/yaptide/pkg/converter"
	"gopkg.in/mgo.v2/bson"
)

func (h *handler) getSimulationResult(
	ctx context.Context,
) (*model.SimulationResult, error) {
	a := extractActionContext(ctx)
	resultID := extractSimulationResultID(ctx)

	result, resultErr := h.Resolver.SimulationResultGet(a, resultID)
	if resultErr != nil {
		return nil, resultErr
	}

	return result, nil
}

func (h *handler) getSimulationSetup(
	ctx context.Context,
) (*model.SimulationSetup, error) {
	a := extractActionContext(ctx)
	setupID := extractSimulationSetupID(ctx)

	setup, setupErr := h.Resolver.SimulationSetupGet(a, setupID)
	if setupErr != nil {
		return nil, setupErr
	}

	return setup, nil
}

func (h *handler) updateSimulationSetup(
	ctx context.Context, input *converter.Setup,
) (*model.SimulationSetup, error) {
	a := extractActionContext(ctx)
	setupID := extractSimulationSetupID(ctx)

	if err := h.Resolver.SimulationSetupUpdate(a, setupID, input); err != nil {
		return nil, err
	}

	setup, getErr := h.Resolver.SimulationSetupGet(a, setupID)
	if getErr != nil {
		return nil, getErr
	}

	return setup, nil
}

func (h *handler) runSimulationHandler(
	ctx context.Context,
	args *struct {
		ProjectID bson.ObjectId `json:"projectId"`
		VersionID int           `json:"versionId"`
	},
) error {
	userID := extractUserID(ctx)
	return h.simulationHandler.HandleSimulation(args.ProjectID, args.VersionID, userID)
}
