package mongo

import (
	"github.com/yaptide/yaptide/errors"
	"gopkg.in/mgo.v2/bson"
)

// ConvertToObjectID ...
func ConvertToObjectID(id string) (binaryID bson.ObjectId, convertErr error) {
	defer func() {
		if err := recover(); err != nil {
			binaryID = ""
			convertErr = errors.ErrNotFound
		}
	}()
	return bson.ObjectIdHex(id), nil
}
