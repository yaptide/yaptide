package cli

import (
	"os/exec"

	"github.com/spf13/cobra"
)

// Launch ...
func Launch() {
	var rootCmd = &cobra.Command{Use: "yaptide-cli"}
	rootCmd.AddCommand(cmdApp, cmdBackend, cmdFrontend, cmdSetup)
	cmdApp.AddCommand(
		generateDevCmd(startDevBackend, startDevFrontend),
		generateTestCmd(testBackend, testFrontend),
		generateCheckCmd(
			checkFrontend, buildBackend, testBackend, lintBackend,
		),
		generateLintCmd(buildBackend, lintBackend, lintFrontend),
	)
	cmdBackend.AddCommand(
		generateDevCmd(startDevBackend),
		generateTestCmd(testBackend),
		generateCheckCmd(buildBackend, testBackend, lintBackend),
		generateLintCmd(buildBackend, lintBackend),
	)
	cmdFrontend.AddCommand(
		generateDevCmd(startDevFrontend),
		generateTestCmd(testFrontend),
		generateCheckCmd(checkFrontend),
		generateLintCmd(lintFrontend),
	)
	if err := rootCmd.Execute(); err != nil {
		log.Error(err)
	}
}

func generateDevCmd(cmds ...func(config) (*exec.Cmd, error)) *cobra.Command {
	return &cobra.Command{
		Use:     "watch",
		Aliases: []string{"dev"},
		Short:   "start in development mode",
		Long:    "starts in development mode with code reloading and development config",
		Args:    cobra.ExactArgs(0),
		Run: func(cmd *cobra.Command, args []string) {
			startCmds(localConfig, cmds...)
		},
	}
}
func generateTestCmd(cmds ...func(config) error) *cobra.Command {
	return &cobra.Command{
		Use:   "test",
		Short: "run tests",
		Args:  cobra.ExactArgs(0),
		Run: func(cmd *cobra.Command, args []string) {
			runCmds(localConfig, cmds...)
		},
	}
}

func generateCheckCmd(cmds ...func(config) error) *cobra.Command {
	return &cobra.Command{
		Use:   "check",
		Short: "run tests, linters, code analysis tools",
		Args:  cobra.ExactArgs(0),
		Run: func(cmd *cobra.Command, args []string) {
			runCmds(localConfig, cmds...)
		},
	}
}

func generateLintCmd(cmds ...func(config) error) *cobra.Command {
	return &cobra.Command{
		Use:   "lint",
		Short: "run linters",
		Args:  cobra.ExactArgs(0),
		Run: func(cmd *cobra.Command, args []string) {
			runCmds(localConfig, cmds...)
		},
	}
}

var cmdBackend = &cobra.Command{
	Use:   "server",
	Short: "server comands",
	Long:  "set of server commands",
	Args:  cobra.ExactArgs(0),
}

var cmdFrontend = &cobra.Command{
	Use:   "client",
	Short: "clients comands",
	Long:  "set of client comands",
	Args:  cobra.ExactArgs(0),
}

var cmdApp = &cobra.Command{
	Use:   "app",
	Short: "application commands",
	Long:  "set of  application comands",
	Args:  cobra.ExactArgs(0),
}

var cmdSetup = &cobra.Command{
	Use:   "setup",
	Short: "install dependencies for an application",
	Long:  "install tools, ensure all dependencies are met, create necessary configuration",
	Args:  cobra.ExactArgs(0),
	Run: func(cmd *cobra.Command, args []string) {
		setupDependicies()
	},
}
