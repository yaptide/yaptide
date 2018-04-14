package model

import (
	"time"

	"github.com/yaptide/app/errors"
	"gopkg.in/mgo.v2/bson"
)

// Project represent named project, which may have multiple version.
type Project struct {
	ID             bson.ObjectId `json:"id" bson:"_id,omitempty"`
	UserID         bson.ObjectId `json:"userId" bson:"userId"`
	ProjectDetails `bson:",inline"`
}

func (p *Project) CreateInitialVersion(
	setupID bson.ObjectId, resultID bson.ObjectId,
) {
	if len(p.Versions) == 0 {
		p.Versions = []Version{
			defaultProjectVersion(setupID, resultID),
		}
	}
}

func (p *Project) CreateFromVersion(
	versionID int, setupID bson.ObjectId, resultID bson.ObjectId,
) error {
	if len(p.Versions) <= versionID {
		return errors.ErrNotFound
	}
	p.Versions = append(
		p.Versions,
		Version{
			ID:        len(p.Versions),
			Status:    New,
			Settings:  p.Versions[versionID].Settings,
			SetupID:   setupID,
			ResultID:  resultID,
			UpdatedAt: time.Now(),
		},
	)
	return nil
}

type ProjectDetails struct {
	Name        string    `json:"name" bson:"name"`
	Description string    `json:"description" bson:"description"`
	Versions    []Version `json:"versions" bson:"versions"`
}

// ProjectCreateInput ...
type ProjectCreateInput struct {
	Name        string
	Description string
}

// Validate ...
func (p ProjectCreateInput) Validate() error {
	return nil
}

// ToProject ...
func (p ProjectCreateInput) ToProject(userID bson.ObjectId) *Project {
	return &Project{
		ID:     bson.NewObjectId(),
		UserID: userID,
		ProjectDetails: ProjectDetails{
			Name:        p.Name,
			Description: p.Description,
		},
	}
}

type ProjectUpdateInput struct {
	Name        *string `json:"name,omitempty"`
	Description *string `json:"description,omitempty"`
}

func (p ProjectUpdateInput) Validate() error {
	return nil
}
