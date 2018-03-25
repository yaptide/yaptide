package result

import (
	"testing"

	test "github.com/yaptide/converter/test"
)

var testCases = test.MarshallingCases{
	{
		&Result{
			Errors: map[string]string{
				"error": "some_error",
			},
		},
		`{
	"errors": {
		"error": "some_error"
	},
	"result_metadata": null,
	"detectors": null
}`,
	},
}

func TestResultMarshal(t *testing.T) {
	test.Marshal(t, testCases)
}

func TestResultUnmarshal(t *testing.T) {
	test.Unmarshal(t, testCases)
}

func TestResultUnmarshalMarshalled(t *testing.T) {
	test.UnmarshalMarshalled(t, testCases)
}

func TestResultMarshalUnmarshalled(t *testing.T) {
	test.MarshalUnmarshalled(t, testCases)
}
