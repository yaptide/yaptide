package utils

import (
	"encoding/json"
	"fmt"
	"reflect"
)

func TypeBasedUnmarshallJSON(
	data []byte, typeMapping map[string]func() interface{},
) (interface{}, error) {
	var detRaw struct {
		Type string `json:"type"`
	}
	if err := json.Unmarshal(data, &detRaw); err != nil {
		return nil, err
	}

	geometryCreate, knownType := typeMapping[detRaw.Type]
	if !knownType {
		return nil, fmt.Errorf("unknown type")
	}
	geometry := geometryCreate()
	if err := json.Unmarshal(data, geometry); err != nil {
		return nil, err
	}
	reflectValue := reflect.ValueOf(geometry)
	if reflectValue.Kind() != reflect.Ptr {
		return nil, fmt.Errorf("invalid input type")
	}
	return reflectValue.Elem().Interface(), nil
}
