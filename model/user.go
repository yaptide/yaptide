package model

import (
	"gopkg.in/mgo.v2/bson"
)

// User contains account login data.
type User struct {
	ID           bson.ObjectId `json:"id,omitempty" bson:"_id"`
	Username     string        `json:"username" bson:"username"`
	Email        string        `json:"email" bson:"email"`
	PasswordHash string        `json:"-" bson:"passwordHash"`
}
