package protocol

import (
	"encoding/json"
	"fmt"
	"reflect"
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestMessagesMarshalling(t *testing.T) {
	testCases := []struct {
		jsonMessage string
		message     interface{}
	}{
		{
			jsonMessage: `{"MessageType":0, "Token":"abc", "AvailableComputingLibrariesNames": ["shield", "fluka"]}`,
			message: &HelloRequestMessage{
				Token: "abc",
				AvailableComputingLibrariesNames: []string{"shield", "fluka"},
			},
		},
		{
			jsonMessage: `{"MessageType":1, "TokenValid": true}`,
			message: &HelloResponseMessage{
				TokenValid: true,
			},
		},
		{
			jsonMessage: `{"MessageType":2, "ComputingLibraryName": "shield", "Files": {"mat.dat": "*", "geo.dat": "**"}}`,
			message: &RunSimulationMessage{
				ComputingLibraryName: "shield",
				Files: map[string]string{
					"mat.dat": "*",
					"geo.dat": "**",
				},
			},
		},
		{
			jsonMessage: `{"MessageType":3, "Files": {"a.dat": "x", "b.dat": "D"}, "Errors": {"some_error": "occured"}}`,
			message: &SimulationResultsMessage{
				Files: map[string]string{
					"a.dat": "x",
					"b.dat": "D",
				},
				Errors: map[string]string{
					"some_error": "occured",
				},
			},
		},
	}

	for _, tc := range testCases {
		t.Run(fmt.Sprintf("%#v", tc.message), func(t *testing.T) {
			t.Run("Message->JSON", func(t *testing.T) {
				expectedJSON, err := json.Marshal(tc.message)
				assert.NoError(t, err)
				assert.JSONEq(t, tc.jsonMessage, string(expectedJSON))
			})

			t.Run("JSON->Message", func(t *testing.T) {
				objType := reflect.TypeOf(tc.message).Elem()
				parsedMessage := reflect.New(objType).Interface()

				err := json.Unmarshal([]byte(tc.jsonMessage), &parsedMessage)
				assert.NoError(t, err)
				assert.Equal(t, tc.message, parsedMessage)
			})
		})
	}
}
