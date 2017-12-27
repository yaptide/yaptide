package main

import (
	"log"
	"net/http"
	"strconv"

	"github.com/yaptide/app/config"
	"github.com/yaptide/app/web"
)

func main() {
	conf := config.SetupConfig()
	log.Printf("Config: %+v\n", *conf)
	router := web.NewRouter(conf)

	portString := ":" + strconv.FormatInt(conf.BackendPort, 10)

	log.Printf("Listening on %v\n", portString)
	log.Fatal(http.ListenAndServe(portString, router))
}
