package web

import (
	"context"
	"encoding/json"
	"fmt"
	"io/ioutil"
	"net/http"
	"reflect"

	"github.com/yaptide/yaptide/errors"
)

type webHandler = func(w http.ResponseWriter, r *http.Request)

func requestWrapper(handlerFunc interface{}) webHandler {
	inputType, validateErr := requestWrapperValidateSignature(handlerFunc)
	if validateErr != nil {
		log.Errorf("[ASSERT][INIT] error in web handler [%s]", validateErr.Error())
		panic(validateErr)
	}

	if inputType == nil {
		return requestWrapperCallContextOnly(reflect.ValueOf(handlerFunc))
	}
	return requestWrapperCallWithBody(reflect.ValueOf(handlerFunc), inputType)
}

func requestWrapperValidateSignature(handler interface{}) (reflect.Type, error) {
	handlerValue := reflect.ValueOf(handler)
	if !handlerValue.IsValid() {
		return nil, fmt.Errorf("handler is not valid [%+v]", handler)
	}

	handlerType := handlerValue.Type()
	if handlerValue.Kind() != reflect.Func {
		return nil, fmt.Errorf("handler %T is not a function", handlerType)
	}

	contextType := reflect.TypeOf((*context.Context)(nil)).Elem()
	if handlerType.NumIn() == 1 {
		if !handlerType.In(0).Implements(contextType) {
			return nil, fmt.Errorf("first argument of %v is not of a type context.Context", handlerType)
		}
	} else if handlerType.NumIn() == 2 {
		if !handlerType.In(0).Implements(contextType) {
			return nil, fmt.Errorf("first argument of %v is not of a type context.Context", handlerType)
		}
		if handlerType.In(1).Kind() != reflect.Ptr {
			return nil, fmt.Errorf("second argument of %v is not ptr", handlerType)
		}
	} else {
		return nil, fmt.Errorf("handler %v has to much arguments %d", handlerType, handlerType.NumIn())
	}

	errorType := reflect.TypeOf((*error)(nil)).Elem()
	if handlerType.NumOut() == 1 {
		if !handlerType.Out(0).Implements(errorType) {
			return nil, fmt.Errorf("first return value of %v doesn't implement error interface", handlerType)
		}
	} else if handlerType.NumOut() == 2 {
		if !handlerType.Out(1).Implements(errorType) {
			return nil, fmt.Errorf("second return value of %v doesn't implement error interface", handlerType)
		}
	} else {
		return nil, fmt.Errorf("handler %v has to much return values %d", handlerType, handlerType.NumOut())
	}

	if handlerType.NumIn() == 2 {
		return handlerType.In(1).Elem(), nil
	}
	return nil, nil
}

func requestWrapperCallWithBody(handler reflect.Value, inputType reflect.Type) webHandler {
	return func(w http.ResponseWriter, r *http.Request) {
		arg := reflect.New(inputType).Interface()
		body, readErr := ioutil.ReadAll(r.Body)
		if readErr != nil {
			handleRequestErr(w, errors.ErrInternalServerError)
		}
		marshalErr := json.Unmarshal(body, &arg)
		if marshalErr != nil {
			handleRequestErr(w, errors.ErrMalformed)
			return
		}
		if arg == nil {
			handleRequestErr(w, errors.ErrMalformed)
			return
		}
		response := handler.Call([]reflect.Value{
			reflect.ValueOf(r.Context()),
			reflect.ValueOf(arg),
		})
		requestWrapperResultHandler(w, response)
	}
}

func requestWrapperCallContextOnly(handler reflect.Value) webHandler {
	return func(w http.ResponseWriter, r *http.Request) {
		response := handler.Call([]reflect.Value{
			reflect.ValueOf(r.Context()),
		})
		requestWrapperResultHandler(w, response)
	}

}

func requestWrapperResultHandler(w http.ResponseWriter, results []reflect.Value) {
	if len(results) == 0 {
		return
	} else if len(results) == 1 {
		if results[0].IsNil() {
			_ = writeJSONResponse(w, http.StatusOK, map[string]string{"status": "ok"})
		} else {
			responseErr := results[0].Interface().(error)
			handleRequestErr(w, responseErr)
		}
	} else if len(results) == 2 {
		if results[1].IsNil() {
			responseObj := results[0].Interface()
			_ = writeJSONResponse(w, http.StatusOK, responseObj)
		} else {
			responseErr := results[1].Interface().(error)
			handleRequestErr(w, responseErr)
		}
	}
}
