package api

import (
	"net/http"
	"net/http/httptest"
	"net/url"
	"testing"
)

func TestHandleGetServerConfig(t *testing.T) {
	requestURI := url.URL{
		Path: "/server_config",
	}

	req, err := http.NewRequest("GET", requestURI.String(), nil)
	if err != nil {
		t.Fatal(err)
	}

	// Create a new recorder to get results.
	rr := httptest.NewRecorder()
	// Run the above request
	Router.ServeHTTP(rr, req)

	// Status should be http.StatusNotFound
	if status := rr.Code; status != http.StatusNotFound {
		t.Errorf("handler returned wrong status code: got %v want %v",
			status, http.StatusOK)
	}
}
