// Package test contains testing utils functions.
package test

import (
	"encoding/json"
	"reflect"
	"testing"

	"github.com/davecgh/go-spew/spew"
	"github.com/sergi/go-diff/diffmatchpatch"
	diff "github.com/yudai/gojsondiff"
	"github.com/yudai/gojsondiff/formatter"
)

func init() {
	spew.Config.DisableMethods = true
	spew.Config.DisableCapacities = true
	spew.Config.DisablePointerMethods = true
	spew.Config.DisablePointerAddresses = true
}

var jsonFormatterConfig = formatter.AsciiFormatterConfig{
	Coloring:       true,
	ShowArrayIndex: true,
}

func DiffJSON(t *testing.T, expected, actual []byte) string {
	t.Helper()

	jsonRaw := map[string]interface{}{}
	if err := json.Unmarshal(expected, &jsonRaw); err != nil {
		t.Errorf("Unable to marshall expected Error[%v]", err)
	}

	diffs, diffErr := diff.New().Compare(expected, actual)
	if diffErr != nil {
		t.Errorf("Unable to calculate diff Error[%v]", diffErr)
	}
	if diffs.Modified() {
		str, err := formatter.NewAsciiFormatter(jsonRaw, jsonFormatterConfig).Format(diffs)
		if err != nil {
			t.Errorf("Unable to format diff in test Error[%v]", err)
		}
		return str
	}
	return ""
}

func DiffModel(t *testing.T, expected, actual interface{}) string {
	t.Helper()
	if reflect.DeepEqual(expected, actual) {
		return ""
	}
	expectedStr := spew.Sdump(expected)
	actualStr := spew.Sdump(actual)

	dump := diffmatchpatch.New()
	diffs := dump.DiffMain(expectedStr, actualStr, true)
	return dump.DiffPrettyText(diffs)
}

// MarshallingCases contains test cases for Marshalling Test functions.
type MarshallingCases []struct {
	Model interface{}

	// JSON which is compared to json.Marshal result.
	// JSON can be in any valid format. Indents and white spaces are ignored.
	JSON string
}

// Marshal run testCases on json.Marshal function.
func Marshal(t *testing.T, testCases MarshallingCases) {
	t.Helper()
	for _, tc := range testCases {
		result, err := json.Marshal(tc.Model)
		if err != nil {
			t.Errorf("Marshall failed with Error[%v]", err)
		}
		if diff := DiffJSON(t, []byte(tc.JSON), result); diff != "" {
			t.Errorf("actual != expected\n%s", diff)
		}
	}
}

// Unmarshal run test cases on json.Unmarshal function.
func Unmarshal(t *testing.T, testCases MarshallingCases) {
	t.Helper()
	for _, tc := range testCases {
		rawInput := []byte(tc.JSON)

		objType := reflect.TypeOf(tc.Model).Elem()
		result := reflect.New(objType).Interface()
		if err := json.Unmarshal(rawInput, &result); err != nil {
			t.Errorf("Marshall failed with Error[%v]", err)
		}

		if diff := DiffModel(t, tc.Model, result); diff != "" {
			t.Errorf("actual != expected\n%s", diff)
		}

	}
}

// UnmarshalMarshalled first Marshal tc.Model, then Unmarshal result from previous operation.
func UnmarshalMarshalled(t *testing.T, testCases MarshallingCases) {
	t.Helper()
	for _, tc := range testCases {
		marshaled, marshallErr := json.Marshal(tc.Model)
		if marshallErr != nil {
			t.Errorf("Marshal failed with Error[%v]", marshallErr)
		}

		objType := reflect.TypeOf(tc.Model).Elem()
		unmarshaled := reflect.New(objType).Interface()
		if err := json.Unmarshal(marshaled, &unmarshaled); err != nil {
			t.Errorf("Unmarshall failed with Error[%v]", err)
		}

		if diff := DiffModel(t, tc.Model, unmarshaled); diff != "" {
			t.Errorf("actual != expected\n%s", diff)
		}
	}
}

// MarshalUnmarshalled first Unmarshal tc.JSON, then Marshal result from previous operation.
func MarshalUnmarshalled(t *testing.T, testCases MarshallingCases) {
	t.Helper()
	for _, tc := range testCases {
		raw := []byte(tc.JSON)
		objType := reflect.TypeOf(tc.Model).Elem()
		unmarshaled := reflect.New(objType).Interface()
		if err := json.Unmarshal(raw, &unmarshaled); err != nil {
			t.Errorf("Unmarshall failed with Error[%v]", err)
		}

		marshaled, marshallErr := json.Marshal(unmarshaled)
		if marshallErr != nil {
			t.Errorf("Marshall failed with Error[%v]", marshallErr)
		}

		if diff := DiffJSON(t, raw, marshaled); diff != "" {
			t.Errorf("actual != expected\n%s", diff)
		}
	}
}
