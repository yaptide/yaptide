package cli

import "fmt"

type config struct {
	frontendPort       int
	backendPort        int
	frontendPublicURL  string
	backendPublicURL   string
	dbUser             string
	dbPassword         string
	dbName             string
	dbHost             string
	dbPort             int
	mongoContainerName string
}

var localConfig = config{
	frontendPort:       3001,
	backendPort:        3002,
	backendPublicURL:   "localhost:3002",
	frontendPublicURL:  "localhost:3001",
	dbName:             "yaptide-local",
	dbHost:             "localhost",
	dbPort:             27017,
	mongoContainerName: "mongodb",
}

func (c config) dbURL() string {
	if c.dbPassword == "" {
		return fmt.Sprintf(
			"mongodb://%s:%d/%s",
			c.dbHost,
			c.dbPort,
			c.dbName,
		)
	}
	return fmt.Sprintf(
		"mongodb://%s:%s@%s:%d/%s",
		c.dbUser,
		c.dbPassword,
		c.dbHost,
		c.dbPort,
		c.dbName,
	)
}
