// Package server provide Context, which contains server "Global Like" structures.
package server

import (
	"crypto/rand"

	"github.com/yaptide/app/config"
	"github.com/yaptide/app/db"
	"github.com/yaptide/app/db/mongo"
	"github.com/yaptide/app/processor"
	"github.com/yaptide/app/web/auth/token"
	"github.com/yaptide/app/web/server/middleware"
)

// Context contains server structures passed to all subrouters
type Context struct {
	Db                   db.Session
	JWTKey               []byte
	ValidationMiddleware middleware.Middleware
	SimulationProcessor  *processor.SimulationProcessor
}

// NewContext constructor create Context using config.Config
func NewContext(conf *config.Config) (*Context, error) {
	session, err := mongo.NewConnection(conf)
	if err != nil {
		return nil, err
	}

	const keySize = 64
	jwtKey := make([]byte, keySize)
	_, err = rand.Read(jwtKey)
	if config.DEVEnv {
		jwtKey = []byte("0")
	}
	if err != nil {
		return nil, err
	}

	validationMiddleware := token.NewValidationMiddleware(jwtKey)

	simulationProcessor := processor.NewProcessor(conf, session)

	return &Context{
		Db:                   session,
		JWTKey:               jwtKey,
		SimulationProcessor:  simulationProcessor,
		ValidationMiddleware: validationMiddleware,
	}, nil
}
