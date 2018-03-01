package mongo

import (
	"gopkg.in/mgo.v2"
	"gopkg.in/mgo.v2/bson"
)

// Document struct used to extract id form mongo documents.
type Document struct {
	ID        bson.ObjectId `bson:"_id"`
	ProjectID bson.ObjectId `bson:"projectId"`
	UserID    bson.ObjectId `bson:"userId"`
}

type collection struct {
	collection *mgo.Collection
}

func (c collection) Bulk() *mgo.Bulk {
	return c.collection.Bulk()
}
func (c collection) Find(query bson.M) *mgo.Query {
	return c.collection.Find(query)
}
func (c collection) FindID(id bson.ObjectId) *mgo.Query {
	return c.collection.FindId(id)
}
func (c collection) Insert(docs ...interface{}) error {
	return c.collection.Insert(docs...)
}
func (c collection) Pipe(pipeline interface{}) *mgo.Pipe {
	return c.collection.Pipe(pipeline)
}
func (c collection) Remove(selector bson.M) error {
	return c.collection.Remove(selector)
}
func (c collection) RemoveAll(selector bson.M) (info *mgo.ChangeInfo, err error) {
	return c.collection.RemoveAll(selector)
}
func (c collection) RemoveID(id bson.ObjectId) error {
	return c.collection.RemoveId(id)
}
func (c collection) Update(selector bson.M, update interface{}) error {
	return c.collection.Update(selector, update)
}
func (c collection) UpdateAll(selector bson.M, update interface{}) (info *mgo.ChangeInfo, err error) {
	return c.collection.UpdateAll(selector, update)
}
func (c collection) UpdateID(id bson.ObjectId, update interface{}) error {
	return c.collection.UpdateId(id, update)
}
func (c collection) Upsert(selector bson.M, update interface{}) (info *mgo.ChangeInfo, err error) {
	return c.collection.Upsert(selector, update)
}
func (c collection) UpsertID(id bson.ObjectId, update interface{}) (info *mgo.ChangeInfo, err error) {
	return c.collection.UpsertId(id, update)
}
