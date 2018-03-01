package mongo

import (
	conf "github.com/yaptide/app/config"
	"gopkg.in/mgo.v2"
	"gopkg.in/mgo.v2/bson"
)

var log = conf.NamedLogger("db")

// OR query tag.
const OR = "$or"

const (
	projectCollection           = "project"
	userCollection              = "user"
	simulationSetupCollection   = "simulationSetup"
	simulationResultsCollection = "simulationResult"
)

// PrimaryKey ...
const PrimaryKey = "_id"

// ProjectForeignKey ...
const ProjectForeignKey = "projectId"

// UserForeignKey ...
const UserForeignKey = "userId"

// UserIDKeyUsername ...
const UserIDKeyUsername = "username"

// UserIDKeyEmail ...
const UserIDKeyEmail = "email"

// DB Database.
type DB struct {
	session          *mgo.Session
	User             func() Collection
	Project          func() Collection
	SimulationSetup  func() Collection
	SimulationResult func() Collection
}

// Close ...
func (db DB) Close() {
	db.session.Close()
}

// Collection ...
type Collection interface {
	Bulk() *mgo.Bulk
	Find(query bson.M) *mgo.Query
	FindID(id bson.ObjectId) *mgo.Query
	Insert(docs ...interface{}) error
	Pipe(pipeline interface{}) *mgo.Pipe
	Remove(selector bson.M) error
	RemoveAll(selector bson.M) (info *mgo.ChangeInfo, err error)
	RemoveID(id bson.ObjectId) error
	Update(selector bson.M, update interface{}) error
	UpdateAll(selector bson.M, update interface{}) (info *mgo.ChangeInfo, err error)
	UpdateID(id bson.ObjectId, update interface{}) error
	Upsert(selector bson.M, update interface{}) (info *mgo.ChangeInfo, err error)
	UpsertID(id bson.ObjectId, update interface{}) (info *mgo.ChangeInfo, err error)
}

// SetupDB ...
func SetupDB(config *conf.Config) (func() DB, error) {
	log.Info("Connecting to db ...")
	session, sessionErr := mgo.Dial(config.DbURL)
	if sessionErr != nil {
		log.Infof("Connection error: %s", sessionErr.Error())
		return nil, sessionErr
	}
	log.Info("Connected")

	log.Info("Ensure indices")
	ensureErr := ensureDBIndices(session.DB(""))
	if ensureErr != nil {
		log.Infof("Ensure indices  error: %s", ensureErr.Error())
		return nil, ensureErr
	}
	session.SetSafe(&mgo.Safe{})
	log.Info("Ensure success")

	return func() DB {
		sessionClone := session.Clone()
		db := session.DB("")
		return DB{
			session: sessionClone,
			User: func() Collection {
				return collection{
					collection: db.C(userCollection),
				}
			},
			Project: func() Collection {
				return collection{
					collection: db.C(projectCollection),
				}
			},
			SimulationSetup: func() Collection {
				return collection{
					collection: db.C(simulationSetupCollection),
				}
			},
			SimulationResult: func() Collection {
				return collection{
					collection: db.C(simulationResultsCollection),
				}
			},
		}
	}, nil
}

func ensureDBIndices(db *mgo.Database) error {
	ensureErrs := []error{
		db.C(userCollection).EnsureIndex(mgo.Index{
			Key: []string{PrimaryKey},
		}),
		db.C(userCollection).EnsureIndex(mgo.Index{
			Key:    []string{UserIDKeyUsername},
			Unique: true,
		}),
		db.C(projectCollection).EnsureIndex(mgo.Index{
			Key: []string{PrimaryKey},
		}),
		db.C(projectCollection).EnsureIndex(mgo.Index{
			Key: []string{UserForeignKey},
		}),
	}
	for _, err := range ensureErrs {
		if err != nil {
			return err
		}
	}
	return nil
}
