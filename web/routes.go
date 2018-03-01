// Package web ...
package web

import (
	"net/http"

	"github.com/go-chi/chi"
	"github.com/yaptide/app/model/action"
)

type handler struct {
	*action.Resolver
}

func setupRoutes(h *handler, db dbProvider, jwt *jwtProvider) (http.Handler, error) {
	w := requestWrapper

	router := chi.NewRouter()

	router.Use(db.middleware)
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

		router.Get("/{setupId}", w(h.getProjectsHandler))
		router.Put("/{setupId}", w(h.updateProjectHandler))
	})

	router.Route("/simulation/results", func(router chi.Router) {
		router.Use(jwt.middleware)

		router.Get("/{resultId}", w(h.getProjectsHandler))
	})
	return router, nil
}
