package config

import (
	"os"

	"github.com/sirupsen/logrus"
)

// NamedLogger creates named package logger.
func NamedLogger(name string) logrus.Logger {
	return logrus.Logger{
		Out: os.Stderr,
		Formatter: &logrus.TextFormatter{
			ForceColors: true,
		},
		Hooks: make(logrus.LevelHooks),
		Level: logrus.DebugLevel,
	}
}
