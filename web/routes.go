// Package web ...
package web

import (
	"net/http"

	"github.com/go-chi/chi"
	"github.com/go-chi/cors"
	"github.com/yaptide/app/model/action"
	"github.com/yaptide/app/simulation"
)

type handler struct {
	*action.Resolver
	simulationHandler *simulation.Handler
}

func setupRoutes(h *handler, db dbProvider, jwt *jwtProvider) (http.Handler, error) {
	w := requestWrapper

	router := chi.NewRouter()
	cors := cors.New(cors.Options{
		AllowedOrigins: []string{"*"},
		AllowedMethods: []string{"GET", "POST", "DELETE", "PUT", "OPTIONS"},
		AllowedHeaders: []string{"Accept", "Authorization", "Content-Type", "X-CSRF-Token"},
	})

	router.Use(db.middleware)
	router.Use(cors.Handler)
	router.Route("/auth", func(router chi.Router) {
		router.Post("/login", w(h.userLoginHandler))
		router.Post("/register", w(h.userRegisterHandler))
	})
	router.Route("/projects", func(router chi.Router) {
		router.Use(jwt.middleware)

		router.Get("/", w(h.getProjectsHandler))
		router.Get("/{projectId}", w(h.getProjectHandler))
		router.Post("/", w(h.createProjectHandler))
		router.Put("/{projectId}", w(h.updateProjectHandler))
		router.Delete("/{projectId}", w(h.removeProjectHandler))
	})
	router.Route("/versions", func(router chi.Router) {
		router.Use(jwt.middleware)

		router.Post("/{projectId}", w(h.createProjectVersionHandler))
		router.Post("/{projectId}/from/{versionId}", w(h.createProjectVersionFromHandler))
		router.Put("/{projectId}/{versionId}", w(h.updateProjectVersionHandler))
	})

	router.Route("/simulation/setup", func(router chi.Router) {
		router.Use(jwt.middleware)

		router.Get("/{setupId}", w(h.getSimulationSetup))
		router.Put("/{setupId}", w(h.updateSimulationSetup))
	})

	router.Route("/simulation/results", func(router chi.Router) {
		router.Use(jwt.middleware)

		router.Get("/{resultId}", w(h.getSimulationResult))
	})

	router.Post("/simulation/run", w(h.runSimulationHandler))
	router.Get("/server_configuration", w(h.getConfiguration))

	return router, nil
}
