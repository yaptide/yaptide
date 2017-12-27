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

// SetupConfig read and check config from various sources
// Close application, if any checkConfig err occurs
func SetupConfig() *Config {
	readEnv()
	conf := getDefaultConfig()

	log.SetLoggerLevel(log.LevelWarning)

	publicUrl := os.Getenv("YAPTIDE_BACKEND_PUBLIC_URL")
	if publicUrl != "" {
		conf.BackendPublicUrl = publicUrl
	} else {
		log.Warning("[config] Public url is not defined. Using default localhost:3002")
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

	dbUrl := os.Getenv("YAPTIDE_DB_URL")
	if dbUrl != "" {
		conf.DbUrl = dbUrl
	} else {
		log.Error("[config] Db url is not defined")
		os.Exit(-1)
	}

	return conf
}

func getDefaultConfig() *Config {
	return &Config{
		BackendPublicUrl: "localhost:3002",
		BackendPort:      3002,
		DbUrl:            "",
	}
}
