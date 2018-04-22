package web

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"runtime/debug"
	"strconv"

	"github.com/go-chi/chi"
	"github.com/yaptide/yaptide/model/action"
	"github.com/yaptide/yaptide/model/mongo"
	"gopkg.in/mgo.v2/bson"
)

type contextKeyType string

const contextUserIDKey contextKeyType = "userId"
const contextDBSessionKey contextKeyType = "dbSession"

func extractActionContext(ctx context.Context) *action.Context {
	return action.NewContext(
		extractDBSession(ctx),
		extractUserID(ctx),
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

func extractUserID(ctx context.Context) bson.ObjectId {
	userIDObj := ctx.Value(contextUserIDKey)
	if userIDObj == nil {
		return ""
	}
	userID, assertOk := userIDObj.(bson.ObjectId)
	if !assertOk {
		log.Errorf("[ASSERT] Wrong type for userId in contex [%+v]", userIDObj)
		debug.PrintStack()
	}
	return userID
}

func extractBsonURLParamIDContext(ctx context.Context, name string) bson.ObjectId {
	chiContext := chi.RouteContext(ctx)
	stringID := chiContext.URLParam(name)
	id, idErr := mongo.ConvertToObjectId(stringID)
	if idErr != nil {
		panic(fmt.Errorf("malformed %s", name))
	}
	return id
}

func extractIntURLParamIDContext(ctx context.Context, name string) int {
	chiContext := chi.RouteContext(ctx)
	stringID := chiContext.URLParam(name)
	id, idErr := strconv.Atoi(stringID)
	if idErr != nil {
		panic(fmt.Errorf("malformed %s", name))
	}
	return id
}

func extractProjectID(ctx context.Context) bson.ObjectId {
	return extractBsonURLParamIDContext(ctx, "projectId")
}
func extractVersionID(ctx context.Context) int {
	return extractIntURLParamIDContext(ctx, "versionId")
}
func extractSimualtionSetupID(ctx context.Context) bson.ObjectId {
	return extractBsonURLParamIDContext(ctx, "setupId")
}
func extractSimulationResultID(ctx context.Context) bson.ObjectId {
	return extractBsonURLParamIDContext(ctx, "resultId")
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
