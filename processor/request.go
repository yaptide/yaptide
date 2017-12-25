package processor

import (
	"github.com/yaptide/app/db"
	"github.com/yaptide/app/model/project"
	"github.com/yaptide/converter/setup"
)

type request interface {
	ConvertModel() error
	StartSimulation() error
	ParseResults()
}

type mainRequestComponent struct {
	session   db.Session
	versionID db.VersionID
	version   project.Version
	setup     setup.Setup
}
