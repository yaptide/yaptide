// Package protocol define structures which are messages passed beetween worked and yaptide.
package protocol

// YaptideListenPath is URI on which yaptide listen for new workers.
const YaptideListenPath = "/ws"

// HelloRequestMessage protocol message.
type HelloRequestMessage struct {
	Token                            string
	AvailableComputingLibrariesNames []string
}

// HelloResponseMessage protocol message.
type HelloResponseMessage struct {
	TokenValid bool
}

// RunSimulationMessage protocol message.
type RunSimulationMessage struct {
	ComputingLibraryName string
	Files                map[string]string
}

// SimulationResultsMessage rotocol message.
type SimulationResultsMessage struct {
	Files  map[string]string `json:",omitempty"`
	Errors []string          `json:",omitempty"`
}
