// Package errors error module.
package errors

import (
	"encoding/json"
	"fmt"
)

var (
	// ErrNotFound error not found.
	ErrNotFound = fmt.Errorf("notfound")
	// ErrUnauthorized error unauthorized request.
	ErrUnauthorized = fmt.Errorf("unauthorized")
	// ErrNotLoggedIn error not logged in.
	ErrNotLoggedIn = fmt.Errorf("notloggedin")
	// ErrMalformed error malformed request.
	ErrMalformed = fmt.Errorf("malformed")
	// ErrExpired token expired error.
	ErrExpired = fmt.Errorf("expired")
	// ErrFormError form error.
	ErrInvalidForm = fmt.Errorf("formerror")
	// ErrInternalServerError Internal Server Error.
	ErrInternalServerError = fmt.Errorf("internal")
	// ErrNotImplemented
	ErrNotImplemented = fmt.Errorf("notimplemented")
)

type FormError map[string]string

func NewFormError() FormError {
	return FormError{"reason": ErrInvalidForm.Error()}
}

func (fe FormError) Error() string {
	return fmt.Sprintf("%+v", fe)
}

func (fe FormError) MarshalJSON() ([]byte, error) {
	return json.Marshal(map[string]string(fe))
}
