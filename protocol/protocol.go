// Package protocol define messages.
package protocol

// YaptideListenPath is URI on witch yaptide listen for new workers.
const YaptideListenPath = "/workerWs"

type HelloRequestMessage struct {
	Token                            string
	AvailableComputingLibrariesNames []string
}

type HelloResponseMessage struct {
	TokenValid bool
}

type RunSimulationMessage struct {
	ComputingLibraryName string
	Files                map[string]string
}

type SimulationResultsMessage struct {
	Files  map[string]string
	Errors map[string]string
}
