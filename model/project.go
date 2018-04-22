package model

import (
	"time"

	"gopkg.in/mgo.v2/bson"
)

// Project represent named project, which may have multiple version.
type Project struct {
	ID             bson.ObjectId `json:"id" bson:"_id,omitempty"`
	UserID         bson.ObjectId `json:"userId" bson:"userId"`
	ProjectDetails `bson:",inline"`
}

// ProjectDetails ...
type ProjectDetails struct {
	Name        string    `json:"name" bson:"name"`
	Description string    `json:"description" bson:"description"`
	Versions    []Version `json:"versions" bson:"versions"`
}

// NewProject ...
func NewProject(userID bson.ObjectId) *Project {
	return &Project{
		ID:     bson.NewObjectId(),
		UserID: userID,
		ProjectDetails: ProjectDetails{
			Versions: []Version{
				Version{
					ID:     0,
					Status: New,
					Settings: Settings{
						SimulationEngine: UnassignedEngine,
						ComputingLibrary: UnassignedLibrary,
					},
					UpdatedAt: time.Now(),
				},
			},
		},
	}
}
