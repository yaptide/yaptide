package config

import (
	"fmt"
	"os"
	"path"
	"runtime"

	"github.com/sirupsen/logrus"
)

// NamedLogger creates named package logger.
func NamedLogger(name string) logrus.Logger {
	return logrus.Logger{
		Out: os.Stderr,
		Formatter: &CustomTextFormatter{
			logrus.TextFormatter{
				ForceColors: true,
			},
		},
		Hooks: make(logrus.LevelHooks),
		Level: logrus.DebugLevel,
	}
}

// CustomTextFormatter ...
type CustomTextFormatter struct {
	logrus.TextFormatter
}

// Format renders a single log entry
func (f *CustomTextFormatter) Format(entry *logrus.Entry) ([]byte, error) {
	_, file, no, _ := runtime.Caller(5)
	entry.Message = fmt.Sprintf("[%-15s:%03d]%s", path.Base(file), no, entry.Message)
	return f.TextFormatter.Format(entry)
}
