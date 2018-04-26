package cli

import (
	"fmt"
	"os"
	"path/filepath"
)

func getPackagePath(module string) (string, error) {
	gopaths := filepath.SplitList(os.Getenv("GOPATH"))
	if len(gopaths) == 0 {
		return "", fmt.Errorf("GOPATH empty")
	}
	if len(gopaths) == 1 {
		return filepath.Join(gopaths[0], "src", module), nil
	}
	return "", fmt.Errorf("Multiple GOPATHs unsupported")
}
