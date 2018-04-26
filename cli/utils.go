package cli

import (
	"os/exec"
)

func runCmds(conf config, cmds ...func(config) error) {
	for _, cmdFunc := range cmds {
		cmdErr := cmdFunc(conf)
		if cmdErr != nil {
			log.Error(cmdErr)
			break
		}
	}
}

func startCmds(conf config, cmds ...func(config) (*exec.Cmd, error)) {
	cmdPool := make([]*exec.Cmd, len(cmds))
	for index, cmdFunc := range cmds {
		cmd, cmdErr := cmdFunc(conf)
		if cmdErr != nil {
			log.Error(cmdErr)
			break
		}
		cmdPool[index] = cmd
	}
	for _, cmd := range cmdPool {
		if cmd != nil {
			if err := cmd.Wait(); err != nil {
				log.Error(err)
				return
			}
		}
	}
}
