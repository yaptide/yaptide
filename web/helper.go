package web

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"runtime/debug"
	"strconv"

	"github.com/go-chi/chi"
	"github.com/yaptide/app/model/action"
	"github.com/yaptide/app/model/mongo"
	"gopkg.in/mgo.v2/bson"
)

type contextKeyType string

const contextUserIDKey contextKeyType = "userId"
const contextDBSessionKey contextKeyType = "dbSession"

func extractActionContext(ctx context.Context) *action.Context {
	return action.NewContext(
		extractDBSession(ctx),
		extractUserId(ctx),
	)
}

func extractDBSession(ctx context.Context) mongo.DB {
	dbSessionObj := ctx.Value(contextDBSessionKey)
	if dbSessionObj == nil {
		log.Error("[ASSERT] Missing db session in context")
		debug.PrintStack()
	}
	dbSession, assertOk := dbSessionObj.(mongo.DB)
	if !assertOk {
		log.Error("[ASSERT] Wrong type for db session")
		debug.PrintStack()
	}
	return dbSession
}

func extractUserId(ctx context.Context) bson.ObjectId {
	userIdObj := ctx.Value(contextUserIDKey)
	if userIdObj == nil {
		return ""
	}
	userId, assertOk := userIdObj.(bson.ObjectId)
	if !assertOk {
		log.Errorf("[ASSERT] Wrong type for userId in contex [%+v]", userIdObj)
		debug.PrintStack()
	}
	return userId
}

func extractBsonURLParamIdContext(ctx context.Context, name string) bson.ObjectId {
	chiContext := chi.RouteContext(ctx)
	stringId := chiContext.URLParam(name)
	id, idErr := mongo.ConvertToObjectId(stringId)
	if idErr != nil {
		panic(fmt.Errorf("malformed %s", name))
	}
	return id
}

func extractIntURLParamIdContext(ctx context.Context, name string) int {
	chiContext := chi.RouteContext(ctx)
	stringID := chiContext.URLParam(name)
	id, idErr := strconv.Atoi(stringID)
	if idErr != nil {
		panic(fmt.Errorf("malformed %s", name))
	}
	return id
}

func extractProjectId(ctx context.Context) bson.ObjectId {
	return extractBsonURLParamIdContext(ctx, "projectId")
}
func extractVersionId(ctx context.Context) int {
	return extractIntURLParamIdContext(ctx, "versionId")
}
func extractSimualtionSetupId(ctx context.Context) bson.ObjectId {
	return extractBsonURLParamIdContext(ctx, "setupId")
}
func extractSimulationResultId(ctx context.Context) bson.ObjectId {
	return extractBsonURLParamIdContext(ctx, "resultId")
}

func writeJSONResponse(w http.ResponseWriter, httpStatus int, body interface{}) error {
	marshaled, marshalingErr := json.Marshal(body)
	if marshalingErr != nil {
		w.WriteHeader(http.StatusInternalServerError)
		return marshalingErr
	}
	w.WriteHeader(httpStatus)
	_, writeErr := w.Write(marshaled)
	return writeErr
}

func decodeJSONRequest(r *http.Request, unpackObject interface{}) error {
	err := json.NewDecoder(r.Body).Decode(unpackObject)
	if err != nil {
		return err
	}
	return nil
}

func handleRequestErr(w http.ResponseWriter, err error) {
	_ = writeJSONResponse(w, http.StatusBadRequest, err.Error())
}
