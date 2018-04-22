package builder

import (
	"fmt"
	"log"
	"os"
)

func Launch() {
	if len(os.Args) == 1 {
		fmt.Print(help)
		return
	}

	switch action := os.Args[1]; action {
	case "dev":
		runCmd(
			localConfig,
			startDevFrontend,
			startDevBackendConverter,
		)
	case "check":
		log.Println("not implemented")
		fmt.Print(help)
	case "docker":
		fmt.Println("not implemented")
		fmt.Print(help)
	case "package":
		fmt.Println("not implemented")
		fmt.Print(help)

	case "setup":
		setupDependicies()

	case "client:only":
		runCmd(
			localConfig,
			startDevFrontend,
		)
	case "server:only":
		runCmd(
			localConfig,
			startDevBackend,
		)
	case "converter:only":
		runCmd(
			localConfig,
			startDevBackendConverter,
		)

	case "client:dev":
		fmt.Println("not implemented")
		fmt.Print(help)
	case "server:dev":
		fmt.Println("not implemented")
		fmt.Print(help)
	case "converter:dev":
		fmt.Println("not implemented")
		fmt.Print(help)

	case "deploy:backend:master":
		deployFromRepo("backend", "https://github.com/yaptide/app.git", "master")
		fmt.Println("not implemented")
		fmt.Print(help)
	case "deploy:backend:develop":
		deployFromRepo("backend", "https://github.com/yaptide/app.git", "develop")
		fmt.Println("not implemented")
		fmt.Print(help)
	case "deploy:backend:staging":
		deployLocal("backend", backendModule)
		fmt.Println("not implemented")
		fmt.Print(help)

	case "deploy:frontend:master":
		deployFromRepo("frontend", "https://github.com/yaptide/ui.git", "master")

		fmt.Println("not implemented")
		fmt.Print(help)
	case "deploy:frontend:develop":
		deployFromRepo("frontend", "https://github.com/yaptide/ui.git", "develop")
		fmt.Println("not implemented")
		fmt.Print(help)
	case "deploy:frontend:staging":
		deployLocal("frontend", frontendModule)
		fmt.Println("not implemented")
		fmt.Print(help)

	case "client:check":
		fmt.Println("not implemented")
		fmt.Print(help)
	case "server:check":
		fmt.Println("not implemented")
		fmt.Print(help)
	case "converter:check":
		fmt.Println("not implemented")
		fmt.Print(help)
	case "client:test":
		fmt.Println("not implemented")
		fmt.Print(help)
	case "server:test":
		fmt.Println("not implemented")
		fmt.Print(help)
	case "converter:test":
		fmt.Println("not implemented")
		fmt.Print(help)
	case "help":
		fallthrough
	default:
		fmt.Print(help)
	}
}

const help = `
Usage: $0 COMMAND [ARGS]

Commands:
	dev				- run everything using current version from GOPATH
	check			- run all checks in every repo
	docker			- setup everything using docker container
	package			- prepare package with compiled app

	client:only		- frontend hot reloading (no server)
	server:only		- server hot reloading (no frontend)
	converter:only	- server with current converter version (no frontend)

	client:dev		- frontend hot reloading (server prod build)
	server:dev		- server hot reloading (frontend prod build)
	converter:dev	- server with current converter version (not from vendor)

	client:check	- ...
	server:check	- ...
	converter:check	- ...

	client:test		- ...
	server:test		- ...
	converter:test	- ...

	help			- displays this info
`
