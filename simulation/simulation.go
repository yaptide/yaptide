// Package processor implements processing all simulation requests. Is responsible for serialization, starting simulation and processing results.
package simulation

import (
	"fmt"

	conf "github.com/yaptide/yaptide/config"
	"github.com/yaptide/yaptide/errors"
	"github.com/yaptide/yaptide/model"
	"github.com/yaptide/yaptide/model/action"
	"github.com/yaptide/yaptide/model/mongo"
	"github.com/yaptide/yaptide/runner/file"
	"gopkg.in/mgo.v2/bson"
)

var log = conf.NamedLogger("simulation_handler")

// Handler responsible for all steps of processing simulation.
type Handler struct {
	action                *action.Resolver
	db                    mongo.DB
	shieldFileLocalRunner *file.Runner
}

// NewProcessor constructor.
func NewHandler(action *action.Resolver, db mongo.DB) *Handler {
	processor := &Handler{
		action: action,
		db:     db,
		shieldFileLocalRunner: file.SetupShieldRunner(action.Config),
	}
	return processor
}

// HandleSimulation processes simulation.
func (p *Handler) HandleSimulation(projectID bson.ObjectId, versionID int, userID bson.ObjectId) error {
	ctx := action.NewContext(p.db, userID)
	project, projectErr := p.action.ProjectGet(ctx, projectID)
	if projectErr != nil {
		log.Warnf("project %s get failed [%s]", projectID.Hex(), projectErr.Error())
		return projectErr
	}
	if len(project.Versions) >= versionID {
		log.Warnf("project %s don't have version %d", projectID.Hex(), versionID)
		return errors.ErrNotFound
	}
	version := project.Versions[versionID]

	setup, setupErr := p.action.SimulationSetupGet(ctx, version.SetupID)
	if setupErr != nil {
		return setupErr
	}

	if err := version.Settings.IsValid(); err != nil {
		return err
	}

	request, requestErr := p.selectRequestFormSettings(version, projectID)
	if requestErr != nil {
		return requestErr
	}

	log.Debug("Start simulation request (serialization)")
	serializeErr := request.ConvertModel(setup)
	if serializeErr != nil {
		return serializeErr
	}

	log.Debug("[SimulationProcessor] Start simulation request (enqueue in runner)")
	startSimulationErr := request.StartSimulation()
	if startSimulationErr != nil {
		return startSimulationErr
	}

	return nil
}

func (h *Handler) selectRequestFormSettings(
	version model.Version, projectID bson.ObjectId,
) (request, error) {
	switch version.Settings.ComputingLibrary {
	case model.ShieldLibrary:
		switch version.Settings.SimulationEngine {
		case model.LocalMachine:
			return &fileRequest{
				Runner:        h.shieldFileLocalRunner,
				fileProcessor: &shieldProcessor{},
				SimulationContext: h.action.NewSimulationContext(
					h.db,
					projectID,
					version.ID,
				),
			}, nil
		default:
			return nil, errors.ErrInternalServerError
		}
	case model.FlukaLibrary:
		return nil, errors.ErrNotImplemented
	default:
		return nil, fmt.Errorf("[SimulationProcessor] Invalid computing library")
	}
}
