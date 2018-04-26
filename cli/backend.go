package cli

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"time"

	"github.com/docker/docker/api/types"
	"github.com/docker/docker/api/types/container"
	"github.com/docker/docker/api/types/network"
	"github.com/docker/docker/client"
	"github.com/docker/go-connections/nat"
)

const backendModule = "github.com/yaptide/yaptide"
const backendAPIModule = "github.com/yaptide/yaptide/cmd/api"

func startDevBackend(conf config) (*exec.Cmd, error) {
	log.Info("Starting yaptide/api ...")
	dockerErr := setupDockerDb(conf)
	if dockerErr != nil {
		log.Error(dockerErr)
		return nil, dockerErr
	}
	absolutePath, getPackageErr := getPackagePath(backendAPIModule)
	if getPackageErr != nil {
		log.Error(getPackageErr)
		return nil, getPackageErr
	}
	cmd := exec.Command(
		"gin",
		"run ./cmd/api/main.go",
		"--port", fmt.Sprintf("%d", conf.backendPort),
		"--appPort", fmt.Sprintf("%d", 15003),
		"--immediate",
	)
	cmd.Dir = absolutePath
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	cmd.Env = os.Environ()
	cmd.Env = append(cmd.Env, fmt.Sprintf("FRONTEND_PUBLIC_URL=%s", conf.backendPublicURL))
	cmd.Env = append(cmd.Env, fmt.Sprintf("PORT=%d", 15003))
	cmd.Env = append(cmd.Env, fmt.Sprintf("DB_URL=%s", conf.dbURL()))
	cmd.Env = append(cmd.Env, fmt.Sprintf("BUILD_ENV=%s", "DEV"))
	if err := cmd.Start(); err != nil {
		log.Error(err)
		return nil, err
	}
	log.Infof("Started yaptide [ENV: %s, PORT: %d]", "DEV", conf.backendPort)
	return cmd, nil
}

func setupDockerDb(conf config) error {
	log.Info("Starting yaptide/api mongo using docker image ...")
	if conf.dbHost != "localhost" {
		err := fmt.Errorf("Unable to setup docker image on remote host")
		log.Error(err)
		return err
	}
	cli, newClientErr := client.NewEnvClient()
	if newClientErr != nil {
		log.Error(newClientErr)
		return newClientErr
	}
	containers, listErr := cli.ContainerList(
		context.Background(), types.ContainerListOptions{All: true},
	)
	if listErr != nil {
		log.Error(listErr)
		return listErr
	}
	for _, container := range containers {
		for _, name := range container.Names {
			if name == fmt.Sprintf("/%s", conf.mongoContainerName) {
				log.Info("Docker container already exists")
				if container.State != "running" {
					startErr := cli.ContainerStart(
						context.Background(),
						container.ID,
						types.ContainerStartOptions{},
					)
					if startErr != nil {
						log.Error(startErr)
						return startErr
					}
					log.Info("Started docker container")
				} else {
					log.Info("Docker container was already running")
				}
				return nil
			}
		}
	}
	log.Info("Creating docker container from image mongo")
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
		conf.mongoContainerName,
	)
	if createErr != nil {
		log.Error(createErr)
		return createErr
	}
	log.Info("Created docker container")
	startErr := cli.ContainerStart(
		context.Background(),
		body.ID,
		types.ContainerStartOptions{},
	)
	if startErr != nil {
		return startErr
	}
	time.Sleep(time.Second * 2)
	log.Info("Started docker container")

	return nil
}

func testBackend(conf config) error {
	absolutePath, pathErr := getPackagePath(backendModule)
	if pathErr != nil {
		log.Error(pathErr)
		return pathErr
	}

	cmd := exec.Command("go", "test", "-tags=\"integration\"", "./...")
	cmd.Dir = absolutePath
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	if err := cmd.Run(); err != nil {
		log.Error(err)
		return err
	}
	return nil
}

func lintBackend(conf config) error {
	absolutePath, pathErr := getPackagePath(backendModule)
	if pathErr != nil {
		log.Error(pathErr)
		return pathErr
	}

	cmd := exec.Command(
		"gometalinter.v2", "--config=.gometalinter.json",
		"--deadline=1000s", "--vendor",
		"./...",
	)
	cmd.Dir = absolutePath
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	if err := cmd.Run(); err != nil {
		log.Error(err)
		return err
	}
	return nil
}

func buildBackend(conf config) error {
	absolutePath, pathErr := getPackagePath(backendModule)
	if pathErr != nil {
		log.Error(pathErr)
		return pathErr
	}

	cmd := exec.Command("go", "build", "./...")
	cmd.Dir = absolutePath
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	if err := cmd.Run(); err != nil {
		log.Error(err)
		return err
	}
	return nil
}
