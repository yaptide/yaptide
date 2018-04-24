// Package web ...
package web

import (
	"net/http"

	"github.com/go-chi/chi"
	"github.com/go-chi/cors"
	"github.com/yaptide/yaptide/model/action"
	"github.com/yaptide/yaptide/simulation"
)

type handler struct {
	*action.Resolver
	simulationHandler *simulation.Handler
}

func setupRoutes(h *handler, db dbProvider, jwt *jwtProvider) (http.Handler, error) {
	w := requestWrapper

	cors := cors.New(cors.Options{
		AllowedOrigins: []string{"*"},
		AllowedMethods: []string{"GET", "POST", "DELETE", "PUT", "OPTIONS"},
		AllowedHeaders: []string{"Accept", "X-Auth-Token", "Content-Type", "X-CSRF-Token"},
	})

	router := chi.NewRouter()
	router.Use(func(next http.Handler) http.Handler {
		handler := func(w http.ResponseWriter, r *http.Request) {
			log.Debugf("[HTTP] %s %s", r.Method, r.URL.Path)
			next.ServeHTTP(w, r)
		}
		return http.HandlerFunc(handler)
	})
	router.Use(db.middleware)
	router.Use(cors.Handler)
	router.Route("/auth", func(router chi.Router) {
		router.Post("/login", w(h.userLoginHandler))
		router.Post("/register", w(h.userRegisterHandler))
	})
	router.Route("/user", func(router chi.Router) {
		router.Use(jwt.middleware)

		router.Get("/", w(h.userGetHandler))
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
		router.Put("/{projectId}/{versionId}/settings", w(h.updateProjectVersionSettingsHandler))
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

	router.Route("/simulation/run", func(router chi.Router) {
		router.Use(jwt.middleware)

		router.Post("/", w(h.runSimulationHandler))
	})
	router.Get("/server_configuration", w(h.getConfiguration))

	return router, nil
}
