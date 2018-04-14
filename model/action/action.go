package action

import (
	conf "github.com/yaptide/app/config"
	"gopkg.in/mgo.v2/bson"
)

var log = conf.NamedLogger("action")

type Resolver struct {
	GenerateToken func(userID bson.ObjectId) (string, error)
	Config        *conf.Config
}
