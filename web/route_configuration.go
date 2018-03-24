package web

import (
	"context"

	"github.com/yaptide/converter/setup/detector"
	"github.com/yaptide/converter/setup/material"
)

func (h *handler) getConfiguration(ctx context.Context) (interface{}, error) {
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

	return response, nil
}
