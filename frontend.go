package builder

import (
	"fmt"
	"os"
	"os/exec"
)

const frontendModule = "github.com/yaptide/ui"

func startDevFrontend(conf config) (*exec.Cmd, error) {
	cmd := exec.Command("npm", "start")
	absolutePath, getPackageErr := getPackagePath(frontendModule)
	if getPackageErr != nil {
		return nil, getPackageErr
	}
	cmd.Dir = absolutePath
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	cmd.Env = os.Environ()
	cmd.Env = append(cmd.Env, fmt.Sprintf("YAPTIDE_BACKEND_PUBLIC_URL=%s", conf.backendPublicUrl))
	cmd.Env = append(cmd.Env, fmt.Sprintf("YAPTIDE_FRONTEND_PORT=%d", conf.frontendPort))
	cmd.Env = append(cmd.Env, fmt.Sprintf("YAPTIDE_FRONTEND_PUBLIC_URL=%s", conf.frontendPublicUrl))

	return cmd, cmd.Start()
}
