package model

import (
	"fmt"
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
	ID          bson.ObjectId `json:"id,omitempty"`
	Name        *string       `json:"project.name,omitempty"`
	Description *string       `json:"project.description,omitempty"`
}

func (p ProjectUpdateInput) Validate() error {
	if p.ID == "" {
		return fmt.Errorf("Missing project id")
	}

	return nil
}

func (p ProjectUpdateInput) ApplyTo(project *Project) {
	if p.Name != nil {
		project.ProjectDetails.Name = *p.Name
	}
	if p.Description != nil {
		project.ProjectDetails.Description = *p.Description
	}
}
