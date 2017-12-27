package config

import (
	"os"
)

func readEnv() {
	env := os.Getenv("YAPTIDE_ENV")
	if env == "PROD" {
		PRODEnv = true
	} else if env == "DEV" {
		DEVEnv = true
	} else {
		PRODEnv = true
	}
}
