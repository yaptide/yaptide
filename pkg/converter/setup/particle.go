package setup

import (
	"encoding/json"
	"fmt"
)

var predefinedParticleTypes = map[string]bool{
	"neutron":          true,
	"proton":           true,
	"pion_pi_minus":    true,
	"pion_pi_plus":     true,
	"pion_pi_zero":     true,
	"he_3":             true,
	"he_4":             true,
	"anti_neutron":     true,
	"anti_proton":      true,
	"kaon_minus":       true,
	"kaon_plus":        true,
	"kaon_zero":        true,
	"kaon_anti":        true,
	"gamma":            true,
	"electron":         true,
	"positron":         true,
	"muon_minus":       true,
	"muon_plus":        true,
	"e_neutrino":       true,
	"e_anti_neutrino":  true,
	"mi_neutrino":      true,
	"mi_anti_neutrino": true,
	"deuteron":         true,
	"triton":           true,
}

// ParticleType ...
type ParticleType interface{}

// Particle is interface for particle scored in detectors.
type Particle struct {
	ParticleType
}

// AllParticles ...
type AllParticles string

// PredefinedParticle ...
type PredefinedParticle string

// HeavyIon ...
type HeavyIon struct {
	Charge        int64 `json:"charge"`
	NucleonsCount int64 `json:"nucleonsCount"`
}

// MarshalJSON json.Marshaller implementation.
func (g PredefinedParticle) MarshalJSON() ([]byte, error) {
	return json.Marshal(struct {
		Type string `json:"type"`
	}{
		Type: string(g),
	})
}

// MarshalJSON ...
func (g AllParticles) MarshalJSON() ([]byte, error) {
	return json.Marshal(struct {
		Type string `json:"type"`
	}{
		Type: "all",
	})
}

// MarshalJSON json.Marshaller implementation.
func (p HeavyIon) MarshalJSON() ([]byte, error) {
	type Alias HeavyIon
	return json.Marshal(struct {
		Type string `json:"type"`
		Alias
	}{
		Type:  "heavy_ion",
		Alias: Alias(p),
	})
}

// MarshalJSON ...
func (p Particle) MarshalJSON() ([]byte, error) {
	return json.Marshal(p.ParticleType)
}

// UnmarshalJSON ...
func (p *Particle) UnmarshalJSON(b []byte) error {
	var rawParticle struct {
		Type string `json:"type"`
	}
	if err := json.Unmarshal(b, &rawParticle); err != nil {
		return err
	}
	switch rawParticle.Type {
	case "all":
		p.ParticleType = AllParticles("all")
	case "heavy_ion":
		var heavyIon HeavyIon
		if err := json.Unmarshal(b, &heavyIon); err != nil {
			return err
		}
		p.ParticleType = heavyIon
	default:
		_, isPredefined := predefinedParticleTypes[rawParticle.Type]
		if !isPredefined {
			return fmt.Errorf("unknown particle type")
		}
		p.ParticleType = PredefinedParticle(rawParticle.Type)
	}
	return nil
}
