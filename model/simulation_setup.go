package model

import (
	"encoding/json"

	"github.com/yaptide/yaptide/pkg/converter"
	"gopkg.in/mgo.v2/bson"
)

// SimulationSetup ...
type SimulationSetup struct {
	ID     bson.ObjectId `json:"id" bson:"_id"`
	UserID bson.ObjectId `json:"userId" bson:"userId"`
	SetupSpec
	MarshalDisabler
}

// InitialSimulationSetup ...
func InitialSimulationSetup(userID bson.ObjectId) *SimulationSetup {
	return &SimulationSetup{
		ID:        bson.NewObjectId(),
		UserID:    userID,
		SetupSpec: SetupSpec{converter.NewEmptySetup()},
	}
}

// MarshalDisabler ...
// very very ugly solution
// TODO refactor that as fast as possible
// temporary fix to enable reversible marshaling of bsons
//
// MarshalDisabler is necessary to make sure that SimulationSetup
// doesn't implement bson.Getter interface. If there are more than one
// implementation of GetBSON method struct is not considered as implementation
// of that interface because actual implementetion is not determined.
type MarshalDisabler struct {
}

// GetBSON ...
func (m MarshalDisabler) GetBSON() (interface{}, error) {
	return nil, nil
}

// SetBSON ...
func (m *MarshalDisabler) SetBSON(raw bson.Raw) error {
	return nil
}

// SetupSpec ...
type SetupSpec struct {
	converter.Setup `bson:",inline"`
}

// GetBSON ...
func (s SetupSpec) GetBSON() (interface{}, error) {
	data, jsonErr := json.Marshal(s)
	if jsonErr != nil {
		return nil, jsonErr
	}
	rawObject := map[string]interface{}{}
	jsonUnmarshallErr := json.Unmarshal(data, &rawObject)
	if jsonUnmarshallErr != nil {
		return nil, jsonUnmarshallErr
	}
	return rawObject, nil
}

// SetBSON ...
func (s *SetupSpec) SetBSON(raw bson.Raw) error {
	var rawMap map[string]interface{}
	bsonUnmarshalErr := raw.Unmarshal(&rawMap)
	if bsonUnmarshalErr != nil {
		return bsonUnmarshalErr
	}
	jsonData, marshalErr := json.Marshal(rawMap)
	if marshalErr != nil {
		return marshalErr
	}

	return json.Unmarshal(jsonData, s)
}
