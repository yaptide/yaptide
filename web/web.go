// Package web ...
package web

import (
	"net/http"

	conf "github.com/yaptide/app/config"
	"github.com/yaptide/app/model/action"
	"github.com/yaptide/app/model/mongo"
	"github.com/yaptide/app/simulation"
)

var log = conf.NamedLogger("web")

// NewRouter ...
func NewRouter(config *conf.Config) (http.Handler, error) {
	dbCreatorFunc, dbErr := mongo.SetupDB(config)
	if dbErr != nil {
		log.Error(dbErr.Error())
		return nil, dbErr
	}

	jwt, jwtErr := newJwtProvider(config)
	if jwtErr != nil {
		log.Error(jwtErr.Error())
		return nil, dbErr
	}

	resolver := &action.Resolver{
		Config:        config,
		GenerateToken: jwt.generate,
	}
	context := &handler{
		Resolver:          resolver,
		simulationHandler: simulation.NewHandler(resolver, dbCreatorFunc()),
	}

	router, setupRoutesErr := setupRoutes(
		context,
		dbProvider(dbCreatorFunc),
		&jwt,
	)
	if setupRoutesErr != nil {
		log.Error(dbErr.Error())
		return nil, setupRoutesErr
	}

	return router, nil
}
