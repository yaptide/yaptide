package protocol

import (
	"encoding/json"
	"errors"
)

type messageType int

type messageTypeObject struct {
	MessageType messageType
}

const (
	helloRequestMessageType = iota
	helloResponseMessageType
	runSimulationMessageType
	simulationResultsMessageType
)

var errBadMessageType = errors.New("Bad MessageType")

// MarshalJSON custom implementation. It encode additional "MessageType" key to distinct message type.
func (m *HelloRequestMessage) MarshalJSON() ([]byte, error) {
	type Alias HelloRequestMessage
	return json.Marshal(struct {
		MessageType messageType
		Alias
	}{
		MessageType: helloRequestMessageType,
		Alias:       (Alias)(*m),
	})
}

// UnmarshalJSON custom implementation. It decode "MessageType" key to perform validation.
func (m *HelloRequestMessage) UnmarshalJSON(b []byte) error {
	messageTypeObject := messageTypeObject{-1}
	err := json.Unmarshal(b, &messageTypeObject)
	if err != nil {
		return err
	}
	if messageTypeObject.MessageType != helloRequestMessageType {
		return errBadMessageType
	}

	type Alias *HelloRequestMessage
	return json.Unmarshal(b, (Alias)(m))
}

// MarshalJSON custom implementation. It encode additional "MessageType" key to distinct message type.
func (m *HelloResponseMessage) MarshalJSON() ([]byte, error) {
	type Alias HelloResponseMessage
	return json.Marshal(struct {
		MessageType messageType
		Alias
	}{
		MessageType: helloResponseMessageType,
		Alias:       (Alias)(*m),
	})
}

// UnmarshalJSON custom implementation. It decode "MessageType" key to perform validation.
func (m *HelloResponseMessage) UnmarshalJSON(b []byte) error {
	messageTypeObject := messageTypeObject{-1}
	err := json.Unmarshal(b, &messageTypeObject)
	if err != nil {
		return err
	}
	if messageTypeObject.MessageType != helloResponseMessageType {
		return errBadMessageType
	}

	type Alias *HelloResponseMessage
	return json.Unmarshal(b, (Alias)(m))
}

// MarshalJSON custom implementation. It encode additional "MessageType" key to distinct message type.
func (m *RunSimulationMessage) MarshalJSON() ([]byte, error) {
	type Alias RunSimulationMessage
	return json.Marshal(struct {
		MessageType messageType
		Alias
	}{
		MessageType: runSimulationMessageType,
		Alias:       (Alias)(*m),
	})
}

// UnmarshalJSON custom implementation. It decode "MessageType" key to perform validation.
func (m *RunSimulationMessage) UnmarshalJSON(b []byte) error {
	messageTypeObject := messageTypeObject{-1}
	err := json.Unmarshal(b, &messageTypeObject)
	if err != nil {
		return err
	}
	if messageTypeObject.MessageType != runSimulationMessageType {
		return errBadMessageType
	}

	type Alias *RunSimulationMessage
	return json.Unmarshal(b, (Alias)(m))
}

// MarshalJSON custom implementation. It encode additional "MessageType" key to distinct message type.
func (m *SimulationResultsMessage) MarshalJSON() ([]byte, error) {
	type Alias SimulationResultsMessage
	return json.Marshal(struct {
		MessageType messageType
		Alias
	}{
		MessageType: simulationResultsMessageType,
		Alias:       (Alias)(*m),
	})
}

// UnmarshalJSON custom implementation. It decode "MessageType" key to perform validation.
func (m *SimulationResultsMessage) UnmarshalJSON(b []byte) error {
	messageTypeObject := messageTypeObject{-1}
	err := json.Unmarshal(b, &messageTypeObject)
	if err != nil {
		return err
	}
	if messageTypeObject.MessageType != simulationResultsMessageType {
		return errBadMessageType
	}

	type Alias *SimulationResultsMessage
	return json.Unmarshal(b, (Alias)(m))
}
