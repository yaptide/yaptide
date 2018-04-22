package setup

import (
	"encoding/json"
	"testing"

	test "github.com/yaptide/converter/test"
)

var opTestCases = test.MarshallingCases{
	{
		&ZoneOperation{BodyID: BodyID(1), Type: Intersect},
		`{"bodyId":1,"type":"intersect"}`,
	},
	{
		&ZoneOperation{BodyID: BodyID(1), Type: Subtract},
		`{"bodyId":1,"type":"subtract"}`,
	},
	{
		&ZoneOperation{BodyID: BodyID(1), Type: Union},
		`{"bodyId":1,"type":"union"}`,
	},
}

func TestOperationMarshal(t *testing.T) {
	test.Marshal(t, opTestCases)
}

func TestOperationUnmarshal(t *testing.T) {
	test.Unmarshal(t, opTestCases)
}

func TestOperationMarshalUnmarshalled(t *testing.T) {
	test.MarshalUnmarshalled(t, opTestCases)
}

func TestOperationUnmarshalMarshalled(t *testing.T) {
	test.UnmarshalMarshalled(t, opTestCases)
}

func TestOperationInvalidTypeMarshal(t *testing.T) {
	testCases := []struct {
		TestOperation *ZoneOperation
		IsReturnErr   bool
	}{
		{
			&ZoneOperation{BodyID: BodyID(1), Type: Subtract},
			false,
		},
		{
			&ZoneOperation{BodyID: BodyID(1), Type: (ZoneOperationType)(10000)},
			true,
		},
	}

	for _, tc := range testCases {
		_, err := json.Marshal(tc.TestOperation)
		if (err != nil) != tc.IsReturnErr {
			t.Errorf("TestOperationInvalidTypeMarshal: IsReturnErr: %v, Actual: %v",
				tc.IsReturnErr, !tc.IsReturnErr)
		}
	}
}

func TestOperationInvalidTypeUnmarshal(t *testing.T) {
	testCases := []struct {
		TestJSON    string
		IsReturnErr bool
	}{
		{
			`{"bodyId":1,"type":"intersect"}`,
			false,
		},
		{
			`{"bodyId":1,"type":"xxxxxxx"}`,
			true,
		},
	}

	for _, tc := range testCases {
		var op ZoneOperation
		err := json.Unmarshal([]byte(tc.TestJSON), &op)
		if (err != nil) != tc.IsReturnErr {
			t.Errorf("TestOperationInvalidTypeUnmarshal: IsReturnErr: %v, Actual: %v",
				tc.IsReturnErr, !tc.IsReturnErr)
		}
	}
}
