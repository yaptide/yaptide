package action

import (
	"github.com/yaptide/yaptide/model"
	"github.com/yaptide/yaptide/model/mongo"
	"github.com/yaptide/yaptide/pkg/converter"
	"gopkg.in/mgo.v2/bson"
)

type SimulationContext struct {
	db             mongo.DB
	actionResolver *Resolver
	projectID      bson.ObjectId
	versionID      int
}

func (r *Resolver) NewSimulationContext(db mongo.DB, projectID bson.ObjectId, versionID int) *SimulationContext {
	return &SimulationContext{
		db:             db,
		actionResolver: r,
		projectID:      projectID,
		versionID:      versionID,
	}
}

func (s *SimulationContext) StatusUpdate(newStatus model.VersionStatus) {

}

func (s *SimulationContext) SetProjectResults(results *converter.Result, simulationErr error) error {
	project := model.Project{}
	getErr := s.db.Project().FindID(s.projectID).One(&project)
	if getErr != nil {
		return getErr
	}
	if simulationErr != nil {
		return s.db.SimulationResult().UpdateID(
			project.Versions[s.versionID].ResultID,
			bson.M{"$set": bson.M{"invalid": simulationErr.Error()}},
		)
	}

	return s.db.SimulationResult().UpdateID(
		project.Versions[s.versionID].ResultID,
		results,
	)
}
