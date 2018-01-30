// Package setup implement
// /projects/{projectId}/versions{versionID}/simulation/setup routes.
package setup

import (
	"net/http"

	"github.com/gorilla/mux"
	"github.com/yaptide/app/web/server"
)

// HandleSetup define simulation setup routes
func HandleSetup(router *mux.Router, context *server.Context) {
	middlewares := context.ValidationMiddleware

	router.Handle("", middlewares(&getSetupHandler{context})).Methods(http.MethodGet)
	router.Handle("", middlewares(&updateSetupHandler{context})).Methods(http.MethodPut)

}
