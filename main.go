package main

import (
	"fmt"
	"net/http"
	"os"

	conf "github.com/yaptide/app/config"
	"github.com/yaptide/app/web"
)

var log = conf.NamedLogger("main")

func main() {
	config, configErr := conf.SetupConfig()
	if configErr != nil {
		log.Errorf("Config error [%s]", configErr.Error())
		os.Exit(-1)
	}

	router, serverCleanup, routerErr := web.SetupWeb(config)
	if routerErr != nil {
		log.Errorf("Setup router error [%s]", configErr.Error())
		os.Exit(-1)
	}
	defer serverCleanup()

	portStr := fmt.Sprintf(":%d", config.BackendPort)
	log.Infof("Serving content on port %d", config.BackendPort)
	listenErr := http.ListenAndServe(portStr, router)
	if listenErr != nil {
		log.Errorf("Server crashed [%s]", listenErr.Error())
		os.Exit(-1)
	}
}
