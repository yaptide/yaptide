package model

import (
	"encoding/json"
	"fmt"
	"time"

	"github.com/yaptide/yaptide/errors"
	"gopkg.in/mgo.v2/bson"
)

// Version is project version, which contains settting and simulation setup/results.
type Version struct {
	ID        int           `json:"id" bson:"_id"`
	Status    VersionStatus `json:"status" bson:"status"`
	Settings  Settings      `json:"settings" bson:"settings"`
	SetupID   bson.ObjectId `json:"setupId" bson:"setupId"`
	ResultID  bson.ObjectId `json:"resultId" bson:"resultId"`
	UpdatedAt time.Time     `json:"updatedAt" bson:"updatedAt"`
}

func (v *Version) UpdateStatus(status VersionStatus) error {
	if v.Status.IsFinal() {
		log.Errorf("[ASSERT] version with status %v shouldn't be updated", v.Status)
		return errors.ErrInternalServerError
	}
	if status == New {
		return fmt.Errorf("can't change status of exisitng version to new")
	}
	v.Status = status
	return nil
}

// VersionStatus indicate current version status.
type VersionStatus int

const (
	//Undefined ...
	Undefined VersionStatus = iota

	// New ...
	New

	// Edited version status. It is set during version modifing.
	Edited

	// Running version status. It is set after simulation start.
	Running

	// Pending version status. It is set after siulation start request.
	Pending

	// Success version status. It is set after successful simulation.
	Success

	// Failure version status. It is set after unsuccessful simulation
	// associated with simulation engine error.
	Failure

	// Interrupted version status. It is set, when simulation processing is interrupted
	// due to technical difficultes like broken connection or server crash.
	Interrupted

	// Canceled version status. It is after request to cancel simulation.
	Canceled

	// Archived version status. It is after creatine new version while old is still editable.
	Archived
)

// IsModifable return true, if simulation has no started yet,
// so Version content can be changed.
func (v VersionStatus) IsModifable() bool {
	return v.IsValid() && !v.IsFinal()
}

// IsRunnable return true, if simulation can be runned.
func (v VersionStatus) IsRunnable() bool {
	return v.IsModifable() && v != New
}

func (v VersionStatus) IsValid() bool {
	return v != Undefined
}

func (v VersionStatus) IsFinal() bool {
	return v == Success || v == Archived
}

func defaultProjectVersion(
	setupID bson.ObjectId, resultID bson.ObjectId,
) Version {
	return Version{
		ID:        0,
		Status:    New,
		Settings:  defaultProjectVersionSettings(),
		SetupID:   setupID,
		ResultID:  resultID,
		UpdatedAt: time.Now(),
	}
}

var mapVersionStatusToJSON = map[VersionStatus]string{
	Undefined:   "",
	New:         "new",
	Edited:      "edited",
	Running:     "running",
	Pending:     "pending",
	Success:     "success",
	Failure:     "failure",
	Interrupted: "interrupted",
	Canceled:    "canceled",
	Archived:    "archived",
}

var mapJSONToVersionStatus = map[string]VersionStatus{
	"":            Undefined,
	"new":         New,
	"edited":      Edited,
	"running":     Running,
	"pending":     Pending,
	"success":     Success,
	"failure":     Failure,
	"interrupted": Interrupted,
	"canceled":    Canceled,
	"archived":    Archived,
}

// String fmt.Stringer implementation.
func (v VersionStatus) String() string {
	return mapVersionStatusToJSON[v]
}

// MarshalJSON json.Marshaller implementation.
func (v VersionStatus) MarshalJSON() ([]byte, error) {
	res, ok := mapVersionStatusToJSON[v]
	if !ok {
		return nil,
			fmt.Errorf("VersionStatus.MarshalJSON: can not convert %v to string", v)
	}
	return json.Marshal(res)
}

// UnmarshalJSON json.Unmarshaller implementation.
func (v *VersionStatus) UnmarshalJSON(b []byte) error {
	var input string
	err := json.Unmarshal(b, &input)
	if err != nil {
		return err
	}

	newVersion, ok := mapJSONToVersionStatus[input]
	log.Println(newVersion, ok)
	if !ok {
		return fmt.Errorf(
			"VersionStatus.UnmarshalJSON: can not convert %s to VersionStatus", input)
	}
	*v = newVersion
	return nil
}
