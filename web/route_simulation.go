package web

import (
	"context"

	"github.com/yaptide/app/model"
	"github.com/yaptide/converter/setup"
	"gopkg.in/mgo.v2/bson"
)

func (h *handler) getSimulationResult(
	ctx context.Context,
) (*model.SimulationResult, error) {
	db := extractDBSession(ctx)
	userID := extractUserId(ctx)
	resultID := extractSimualtionSetupId(ctx)

	result, resultErr := h.Resolver.SimulationResultGet(db, resultID, userID)
	if resultErr != nil {
		return nil, resultErr
	}

	return result, nil
}

func (h *handler) getSimulationSetup(
	ctx context.Context,
) (*model.SimulationSetup, error) {
	db := extractDBSession(ctx)
	userID := extractUserId(ctx)
	setupID := extractSimualtionSetupId(ctx)

	setup, setupErr := h.Resolver.SimulationSetupGet(db, setupID, userID)
	if setupErr != nil {
		return nil, setupErr
	}

	return setup, nil
}

func (h *handler) updateSimulationSetup(
	input *setup.Setup,
	ctx context.Context,
) (*model.SimulationSetup, error) {
	db := extractDBSession(ctx)
	userID := extractUserId(ctx)
	setupID := extractSimualtionSetupId(ctx)

	setup, getErr := h.Resolver.SimulationSetupGet(db, setupID, userID)
	if getErr != nil {
		return nil, getErr
	}

	setup, setupErr := h.Resolver.SimulationSetupUpdate(db, setup, input)
	if setupErr != nil {
		return nil, setupErr
	}

	return setup, nil
}

func (h *handler) runSimulationHandler(
	args *struct {
		ProjectID bson.ObjectId `json:"projectId"`
		VersionID int           `json:"versionId"`
	},
	ctx context.Context,
) error {
	userID := extractUserId(ctx)
	return h.simulationHandler.HandleSimulation(args.ProjectID, args.VersionID, userID)
}
