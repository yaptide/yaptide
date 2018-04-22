package web

import (
	"context"
	"crypto/rand"
	"net/http"
	"time"

	"github.com/dgrijalva/jwt-go"
	conf "github.com/yaptide/yaptide/config"
	"github.com/yaptide/yaptide/errors"
	"github.com/yaptide/yaptide/model/mongo"
	"gopkg.in/mgo.v2/bson"
)

type jwtProvider struct {
	jwtKey []byte
	header string
}

func newJwtProvider(config *conf.Config) (jwtProvider, error) {
	const keySize = 64
	jwtKey := make([]byte, keySize)
	_, err := rand.Read(jwtKey)
	if err != nil {
		return jwtProvider{}, err
	}
	return jwtProvider{
		jwtKey: []byte("rwfwer"), // TODO: constant key in dev environment
		header: "X-Auth-Token",
	}, nil
}

func (jp jwtProvider) generate(id bson.ObjectId) (string, error) {
	token := jwt.New(jwt.SigningMethodHS256)
	claims := token.Claims.(jwt.MapClaims)

	claims["id"] = id
	claims["exp"] = time.Now().Add(time.Hour * 2400).Unix()

	return token.SignedString(jp.jwtKey)
}

func (jp jwtProvider) middleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {

		token := r.Header.Get(jp.header)
		if token == "" {
			log.Info("Missing auth token")
			_ = writeJSONResponse(w, http.StatusUnauthorized, map[string]string{
				"reason": errors.ErrNotLoggedIn.Error(),
			})
			return
		}

		parsed, parseErr := jwt.Parse(token, func(*jwt.Token) (interface{}, error) {
			return jp.jwtKey, nil
		})
		if validationErr, ok := parseErr.(*jwt.ValidationError); ok &&
			validationErr.Errors&jwt.ValidationErrorExpired != 0 {
			log.Warn("token expired")
			_ = writeJSONResponse(w, http.StatusUnauthorized, map[string]string{
				"reason": errors.ErrExpired.Error(),
			})
			return
		}
		if parseErr != nil {
			log.Warn("Unable to parse token %s", parseErr.Error())
			handleRequestErr(w, errors.ErrMalformed)
			return
		}

		claims, assertTypeOk := parsed.Claims.(jwt.MapClaims)
		if !parsed.Valid || !assertTypeOk {
			log.Warn("Token is not valid")
			_ = writeJSONResponse(w, http.StatusUnauthorized, map[string]string{
				"reason": errors.ErrMalformed.Error(),
			})
			return
		}

		converted, convertErr := mongo.ConvertToObjectId(claims["id"].(string))
		if convertErr != nil {
			handleRequestErr(w, errors.ErrMalformed)
			return
		}

		idKey := contextUserIDKey
		idVal := converted

		ctx := context.WithValue(r.Context(), idKey, idVal)
		next.ServeHTTP(w, r.WithContext(ctx))
	})
}
