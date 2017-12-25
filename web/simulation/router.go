// Package simulation implement /simulation routes.
package simulation

import (
	"net/http"

	"github.com/gorilla/mux"

	"github.com/yaptide/app/web/server"
)

// HandleSimulation define simulation routes.
func HandleSimulation(router *mux.Router, context *server.Context) {
	middlewares := context.ValidationMiddleware
	router.Handle("/run", middlewares(&runSimulationHandler{context})).Methods(http.MethodPost)
}
