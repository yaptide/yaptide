package action

import (
	conf "github.com/yaptide/yaptide/config"
	"github.com/yaptide/yaptide/model/mongo"
	"gopkg.in/mgo.v2/bson"
)

var log = conf.NamedLogger("action")

// M ...
type M = bson.M

// Context ...
type Context struct {
	userID bson.ObjectId
	db     mongo.DB
}

type context = Context

// NewContext ...
func NewContext(db mongo.DB, userID bson.ObjectId) *Context {
	return &Context{
		userID: userID,
		db:     db,
	}
}

// UserID ...
func (c Context) UserID() bson.ObjectId {
	return c.userID
}

// DB ...
func (c Context) DB() mongo.DB {
	return c.db
}

// Resolver ...
type Resolver struct {
	GenerateToken func(userID bson.ObjectId) (string, error)
	Config        *conf.Config
}
