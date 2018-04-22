package setup

import (
	"encoding/json"
	"fmt"
)

// ZoneOperationType determines operation type.
// OperationTypes are based on mathematical operations on sets.
type ZoneOperationType int

const (
	// Intersect operation: A ∩ B.
	Intersect ZoneOperationType = iota
	// Subtract operation: A \ B.
	Subtract
	// Union operation: A ∪ B.
	Union
)

var mapOperationToJSON = map[ZoneOperationType]string{
	Intersect: "intersect",
	Subtract:  "subtract",
	Union:     "union",
}

var mapJSONToOperation = map[string]ZoneOperationType{
	"intersect": Intersect,
	"subtract":  Subtract,
	"union":     Union,
}

// ZoneOperation determines construction of Zone.
type ZoneOperation struct {
	BodyID BodyID            `json:"bodyId"`
	Type   ZoneOperationType `json:"-"`
}

type rawOperation struct {
	BodyID BodyID `json:"bodyId"`
	Type   string `json:"type"`
}

// MarshalJSON custom Marshal function.
func (o *ZoneOperation) MarshalJSON() ([]byte, error) {

	typeStr, ok := mapOperationToJSON[o.Type]
	if !ok {
		return nil, fmt.Errorf("Operation.MarshalJSON: can not convert OperationType: %v to string",
			o.Type)

	}
	return json.Marshal(&rawOperation{
		BodyID: o.BodyID,
		Type:   typeStr,
	})
}

// UnmarshalJSON custom Unmarshal function.
func (o *ZoneOperation) UnmarshalJSON(b []byte) error {
	rOperation := rawOperation{}
	err := json.Unmarshal(b, &rOperation)
	if err != nil {
		return err
	}

	operationType, ok := mapJSONToOperation[rOperation.Type]
	if !ok {
		return fmt.Errorf("Operation.UnmarshalJSON: can not convert string: %v to OperationType",
			o.Type)
	}
	o.BodyID = rOperation.BodyID
	o.Type = operationType
	return nil
}
