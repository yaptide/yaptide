package web

import (
	"context"
	"net/http"

	"github.com/yaptide/yaptide/model/mongo"
)

type dbProvider func() mongo.DB

func (p dbProvider) middleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		db := p()
		defer db.Close()

		newCtx := context.WithValue(
			r.Context(),
			contextDBSessionKey,
			db,
		)
		updatedRequest := r.WithContext(newCtx)
		next.ServeHTTP(w, updatedRequest)
	})
}
