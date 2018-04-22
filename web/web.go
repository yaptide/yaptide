// Package web ...
package web

import (
	"net/http"

	conf "github.com/yaptide/yaptide/config"
	"github.com/yaptide/yaptide/model/action"
	"github.com/yaptide/yaptide/model/mongo"
	"github.com/yaptide/yaptide/simulation"
	mgo "gopkg.in/mgo.v2"
)

var log = conf.NamedLogger("web")

// SetupWeb ...
func SetupWeb(config *conf.Config) (http.Handler, func(), error) {
	session, dbErr := mongo.ConnectDB(config)
	if dbErr != nil {
		log.Error(dbErr.Error())
		return nil, func() {}, dbErr
	}

	return NewRouter(config, session)
}

// NewRouter ...
func NewRouter(config *conf.Config, session *mgo.Session) (http.Handler, func(), error) {

	dbCreatorFunc, dbErr := mongo.SetupDB(config, session)
	if dbErr != nil {
		log.Error(dbErr.Error())
		return nil, func() {}, dbErr
	}

	jwt, jwtErr := newJwtProvider(config)
	if jwtErr != nil {
		log.Error(jwtErr.Error())
		return nil, func() {}, jwtErr
	}

	resolver := &action.Resolver{
		Config:        config,
		GenerateToken: jwt.generate,
	}
	simulationHandlerSession := dbCreatorFunc()
	context := &handler{
		Resolver:          resolver,
		simulationHandler: simulation.NewHandler(resolver, simulationHandlerSession),
	}

	router, setupRoutesErr := setupRoutes(
		context,
		dbProvider(dbCreatorFunc),
		&jwt,
	)
	if setupRoutesErr != nil {
		log.Error(dbErr.Error())
		return nil, func() {}, setupRoutesErr
	}
	return router, func() {
		simulationHandlerSession.Close()
	}, nil
}
