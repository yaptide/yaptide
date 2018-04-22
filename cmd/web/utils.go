package builder

import (
	"fmt"
	"log"
	"os/exec"
)

type config struct {
	frontendPort      int
	backendPort       int
	frontendPublicUrl string
	backendPublicUrl  string
	dbUser            string
	dbPassword        string
	dbName            string
	dbHost            string
	dbPort            int
}

var localConfig = config{
	frontendPort:      3001,
	backendPort:       3002,
	backendPublicUrl:  "localhost:3002",
	frontendPublicUrl: "localhost:3001",
	dbUser:            "yaptide",
	dbPassword:        "password",
	dbName:            "yaptide-local",
	dbHost:            "localhost",
	dbPort:            3003,
}

func (c config) dbUrl() string {
	return fmt.Sprintf(
		"mongodb://%s:%s@%s:%d/%s",
		c.dbUser,
		c.dbPassword,
		c.dbHost,
		c.dbPort,
		c.dbName,
	)
}

func runCmd(conf config, cmds ...func(config) (*exec.Cmd, error)) {
	cmdPool := make([]*exec.Cmd, len(cmds))
	for index, cmdFunc := range cmds {
		cmd, cmdErr := cmdFunc(conf)
		if cmdErr != nil {
			log.Println(cmdErr.Error())
			break
		}
		cmdPool[index] = cmd
	}
	for _, cmd := range cmdPool {
		if cmd != nil {
			cmd.Wait()
		}
	}
}
