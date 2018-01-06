package config

import (
	"github.com/yaptide/app/log"
	"os"
	"strconv"
)

// PRODEnv - current environment
var PRODEnv = false

// DEVEnv - current environment
var DEVEnv = false

// Config contains basic server configuration
type Config struct {
	FrontendPublicURL string
	BackendPort       int64
	DbURL             string
}

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

// SetupConfig read and check config from various sources
// Close application, if any checkConfig err occurs
func SetupConfig() *Config {
	readEnv()
	conf := getDefaultConfig()

	log.SetLoggerLevel(log.LevelWarning)

	frontendPublicURL := os.Getenv("YAPTIDE_FRONTEND_PUBLIC_URL")
	if frontendPublicURL != "" {
		conf.FrontendPublicURL = frontendPublicURL
	} else {
		log.Warning("[config] Public frontend url is not defined. Using default localhost:3001")
	}

	port := os.Getenv("YAPTIDE_BACKEND_PORT")
	if port != "" {
		portNumber, numberErr := strconv.ParseInt(port, 10, 64)
		if numberErr != nil {
			log.Error("[config] Port is not a number. %s", numberErr.Error())
		} else {
			conf.BackendPort = portNumber
		}
	} else {
		log.Warning("[config] Backend port is not defined. Using default 3002")
	}

	dbURL := os.Getenv("YAPTIDE_DB_URL")
	if dbURL != "" {
		conf.DbURL = dbURL
	} else {
		log.Error("[config] Db url is not defined")
		os.Exit(-1)
	}

	return conf
}

func getDefaultConfig() *Config {
	return &Config{
		FrontendPublicURL: "localhost:3001",
		BackendPort:       3002,
		DbURL:             "",
	}
}
