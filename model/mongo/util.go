package mongo

import (
	"github.com/yaptide/yaptide/errors"
	"gopkg.in/mgo.v2/bson"
)

func ConvertToObjectId(id string) (binaryId bson.ObjectId, convertErr error) {
	defer func() {
		if err := recover(); err != nil {
			binaryId = ""
			convertErr = errors.ErrNotFound
		}
	}()
	return bson.ObjectIdHex(id), nil
}
