package action

import (
	conf "github.com/yaptide/app/config"
	"gopkg.in/mgo.v2/bson"
)

type Resolver struct {
	GenerateToken func(userID bson.ObjectId) (string, error)
	Config        *conf.Config
}
