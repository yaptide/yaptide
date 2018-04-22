package mapping

import (
	"fmt"

	"github.com/yaptide/yaptide/pkg/converter/setup"
)

// ParticleToShield map Particle to shield format.
func ParticleToShield(particle setup.Particle) (int64, error) {
	switch p := particle.ParticleType.(type) {
	case setup.PredefinedParticle:
		number, ok := predefinedParticleToShieldMapping[p]
		if ok {
			return number, nil
		}
		return int64(0), fmt.Errorf("Unsuported particle type %T", particle)
	case setup.HeavyIon:
		return int64(25), nil
	}
	return int64(0), fmt.Errorf("Unsuported particle type %T", particle)
}

var predefinedParticleToShieldMapping = map[setup.PredefinedParticle]int64{
	"all":              -1,
	"neutron":          1,
	"proton":           2,
	"pion_pi_minus":    3,
	"pion_pi_plus":     4,
	"pion_pi_zero":     5,
	"anti_neutron":     6,
	"anti_proton":      7,
	"kaon_minus":       8,
	"kaon_plus":        9,
	"kaon_zero":        10,
	"kaon_anti":        11,
	"gamma":            12,
	"electron":         13,
	"positron":         14,
	"muon_minus":       15,
	"muon_plus":        16,
	"e_neutrino":       17,
	"e_anti_neutrino":  18,
	"mi_neutrino":      19,
	"mi_anti_neutrino": 20,
	"deuteron":         21,
	"triton":           22,
	"he_3":             23,
	"he_4":             24,
}

// ScoringToShield ...
func ScoringToShield(scoringType setup.DetectorScoring) (string, error) {
	switch scoring := scoringType.ScoringType.(type) {
	case setup.PredefinedScoring:
		name, found := scoringToShield[string(scoring)]
		if !found {
			return "", fmt.Errorf("Unsuported scoring type %s", scoring)
		}
		return name, nil
	case setup.LetTypeScoring:
		name, found := scoringToShield[scoring.Type]
		if !found {
			return "", fmt.Errorf("Unsuported scoring type %s", scoring.Type)
		}
		return name, nil
	}
	return "", fmt.Errorf("Unsuported scoring type %T", scoringType)
}

var scoringToShield = map[string]string{
	"energy":     "ENERGY",
	"fluence":    "FLUENCE",
	"crossflu":   "CROSSFLU",
	"dose":       "DOSE",
	"letflu":     "LETFLU",
	"dlet":       "DLET",
	"tlet":       "TLET",
	"avg_energy": "AVG-ENERGY",
	"avg_beta":   "AVG-BETA",
	"ddd":        "DDD",
	"spc":        "SPC",
	"alanine":    "ALANINE",
	"counter":    "COUNTER",
}
