package web

import (
	"net/http"

	"github.com/yaptide/app/config"
	"github.com/yaptide/app/web/server"
	"github.com/yaptide/app/web/util"
	"github.com/yaptide/converter/setup/detector"
	"github.com/yaptide/converter/setup/material"
)

type getConfigurationHandler struct {
	*server.Context
	*config.Config
}

func (h *getConfigurationHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	var response struct {
		PredefinedMaterials []material.PredefinedMaterialRecord `json:"predefinedMaterials"`
		Isotopes            []material.IsotopeRecord            `json:"isotopes"`
		ParticleTypes       []detector.PredefinedParticleRecord `json:"particles"`
		ScoringTypes        []detector.ScoringTypeRecord        `json:"scoringTypes"`
	}

	response.PredefinedMaterials = material.PredefinedMaterials()
	response.Isotopes = material.Isotopes()
	response.ParticleTypes = detector.ParticleTypes()
	response.ScoringTypes = detector.ScoringTypes()

	util.WriteJSONResponse(w, http.StatusOK, response)
}
