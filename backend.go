package builder

import (
	"context"
	"fmt"
	"github.com/docker/docker/api/types"
	"github.com/docker/docker/api/types/container"
	"github.com/docker/docker/api/types/network"
	"github.com/docker/docker/client"
	"github.com/docker/go-connections/nat"
	"os"
	"os/exec"
	"path/filepath"
	"time"
)

const backendModule = "github.com/yaptide/app"
const converterModule = "github.com/yaptide/converter"

func startDevBackend(conf config) (*exec.Cmd, error) {
	dockerErr := setupDockerDb(conf)
	if dockerErr != nil {
		return nil, dockerErr
	}
	absolutePath, getPackageErr := getPackagePath(backendModule)
	if getPackageErr != nil {
		return nil, getPackageErr
	}
	cmd := exec.Command(
		"gin",
		"--port", fmt.Sprintf("%d", conf.backendPort),
		"--appPort", fmt.Sprintf("%d", 15003),
		"--immediate",
	)
	cmd.Dir = absolutePath
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	cmd.Env = os.Environ()
	cmd.Env = append(cmd.Env, fmt.Sprintf("YAPTIDE_FRONTEND_PUBLIC_URL=%s", conf.backendPublicUrl))
	cmd.Env = append(cmd.Env, fmt.Sprintf("YAPTIDE_BACKEND_PORT=%d", 15003))
	cmd.Env = append(cmd.Env, fmt.Sprintf("YAPTIDE_DB_URL=%s", conf.dbUrl()))
	return cmd, cmd.Start()
}

func ensureDeps(importPath string) error {
	cmd := exec.Command("dep", "ensure")
	absolutePath, getPackageErr := getPackagePath(importPath)
	if getPackageErr != nil {
		return getPackageErr
	}
	cmd.Dir = absolutePath
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	return cmd.Run()
}

func startDevBackendConverter(conf config) (*exec.Cmd, error) {
	modulePath, getPackageErr := getPackagePath(backendModule)
	if getPackageErr != nil {
		return nil, getPackageErr
	}
	depPath := filepath.Join(modulePath, "vendor", converterModule)
	removeErr := os.RemoveAll(depPath)
	if removeErr != nil {
		return nil, removeErr
	}
	return startDevBackend(conf)
}

func startDevBackendOnly(conf config) (*exec.Cmd, error) {
	ensureErr := ensureDeps(backendModule)
	if ensureErr != nil {
		return nil, ensureErr
	}
	return startDevBackend(conf)
}

func createFile(path string, content string) error {
	file, createErr := os.Create(path)
	if createErr != nil {
		return createErr
	}
	_, writeErr := file.Write([]byte(content))
	return writeErr
}

func setupDockerDb(conf config) error {
	if conf.dbHost != "localhost" {
		return fmt.Errorf("unable to setup docker iamge on remote host")
	}
	cli, err := client.NewEnvClient()
	if err != nil {
		panic(err)
	}
	containers, listErr := cli.ContainerList(context.Background(), types.ContainerListOptions{All: true})
	if listErr != nil {
		return listErr
	}
	for _, container := range containers {
		for _, name := range container.Names {
			if name == "/yaptide_db_local" {
				fmt.Println("Docker exists")
				if container.State != "running" {
					startErr := cli.ContainerStart(context.Background(), container.ID, types.ContainerStartOptions{})
					if startErr != nil {
						return startErr
					}
				}
				return nil
			}
		}
	}
	fmt.Println("Docker create")
	body, createErr := cli.ContainerCreate(
		context.Background(),
		&container.Config{
			Image: "mongo",
		},
		&container.HostConfig{
			PortBindings: nat.PortMap(
				map[nat.Port][]nat.PortBinding{
					nat.Port(fmt.Sprintf("%d/tcp", 27017)): []nat.PortBinding{
						nat.PortBinding{HostPort: fmt.Sprintf("%d", conf.dbPort)},
					},
				},
			),
		},
		&network.NetworkingConfig{},
		"yaptide_db_local",
	)
	if createErr != nil {
		return createErr
	}
	startErr := cli.ContainerStart(
		context.Background(),
		body.ID,
		types.ContainerStartOptions{},
	)
	if startErr != nil {
		return startErr
	}

	time.Sleep(time.Second * 4)
	setupCmd := fmt.Sprintf("docker exec yaptide_db_local mongo admin --eval 'db.createUser({ user: \"root\", pwd: \"password\", roles: [ { role: \"root\", db: \"admin\" } ] });'")
	userCmd := fmt.Sprintf("%s '%s'",
		"docker exec yaptide_db_local mongo admin -u root -p password --eval",
		fmt.Sprintf(
			"db.getSiblingDB(\"%s\").createUser({ user: \"%s\", pwd: \"%s\", roles: [ { role: \"readWrite\", db: \"%s\" }] });",
			conf.dbName,
			conf.dbUser,
			conf.dbPassword,
			conf.dbName,
		),
	)
	setupCommand := exec.Command(
		"bash",
		"-c",
		setupCmd,
	)
	setupCommand.Stdout = os.Stdout
	setupCommand.Stderr = os.Stderr
	if err := setupCommand.Run(); err != nil {
		return nil
	}

	userCommand := exec.Command(
		"bash",
		"-c",
		userCmd,
	)
	userCommand.Stdout = os.Stdout
	userCommand.Stderr = os.Stderr
	if err := userCommand.Run(); err != nil {
		return nil
	}

	return nil
}
