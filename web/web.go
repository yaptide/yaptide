// Package web ...
package web

import (
	"net/http"

	conf "github.com/yaptide/app/config"
	"github.com/yaptide/app/model/action"
	"github.com/yaptide/app/model/mongo"
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

	context := &handler{
		Resolver: &action.Resolver{
			Config:        config,
			GenerateToken: jwt.generate,
		},
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
