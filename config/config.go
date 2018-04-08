// Package config provide config from command-line.
package config

import (
	"flag"
	"fmt"
	"os"
	"regexp"
	"strings"
)

// Config represent worker configuration.
type Config struct {
	Token string

	Address string

	LoggingLevel string
}

// Read config from command-line.
// It call os.Exit, if config is incorrect.
func Read() Config {
	config := Config{}

	flag.StringVar(&config.Address, "address", "", "yaptide host:port")
	flag.StringVar(&config.LoggingLevel, "logging-level", "info", "logging level, one of: "+availableLoggingLevelsString)
	flag.StringVar(&config.Token, "token", "", "token used for authentication")
	flag.Parse()

	config.LoggingLevel = strings.ToLower(config.LoggingLevel)

	invalidConfig := false
	if !regexp.MustCompile(`^.*?:\d+$`).MatchString(config.Address) {
		fmt.Fprintf(os.Stderr, "Invalid address: \"%s\"\n", config.Address)
		invalidConfig = true
	}

	if !validateLoggingLevel(config.LoggingLevel) {
		fmt.Fprintf(os.Stderr, "Invalid loggingLevel: \"%s\"\n", config.LoggingLevel)
		invalidConfig = true
	}

	if config.Token == "" {
		fmt.Fprintf(os.Stderr, "Invalid token: \"%s\"\n", config.Token)
		invalidConfig = true
	}

	if invalidConfig {
		fmt.Fprintf(os.Stderr, "\n")
		flag.Usage()
		os.Exit(1)
	}

	return config
}

var availableLoggingLevels = []string{"panic", "fatal", "error", "warn", "info", "debug"}
var availableLoggingLevelsString = strings.Join(availableLoggingLevels, ", ")

func validateLoggingLevel(loggingLevel string) bool {
	for _, l := range availableLoggingLevels {
		if l == loggingLevel {
			return true
		}
	}
	return false
}
