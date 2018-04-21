package action

import (
	conf "github.com/yaptide/app/config"
	"github.com/yaptide/app/model/mongo"
	"gopkg.in/mgo.v2/bson"
)

var log = conf.NamedLogger("action")

type M = bson.M

type Context struct {
	userID bson.ObjectId
	db     mongo.DB
}

type context = Context

func NewContext(db mongo.DB, userID bson.ObjectId) *Context {
	return &Context{
		userID: userID,
		db:     db,
	}
}

func (c Context) UserID() bson.ObjectId {
	return c.userID
}

func (c Context) DB() mongo.DB {
	return c.db
}

type Resolver struct {
	GenerateToken func(userID bson.ObjectId) (string, error)
	Config        *conf.Config
}
