package setup

import (
	"testing"

	"github.com/yaptide/converter/setup"
)

func TestPredefinedMaterialsToShieldICRUMapping(t *testing.T) {
	for _, predefinedMaterial := range setup.PredefinedMaterials() {
		_, found := predefinedMaterialsToShieldICRU[predefinedMaterial.Value]
		if !found {
			t.Errorf("PredefinedMaterial mapping to Shield ICRU for \"%s\" not found", predefinedMaterial.Value)
		}
	}
}

func TestIsotopeToShieldNUCLIDMapping(t *testing.T) {
	for _, isotope := range setup.Isotopes() {
		_, found := isotopesToShieldNUCLID[isotope.Value]
		if !found {
			t.Errorf("Isotope mapping to Shield NUCLID for \"%s\" not found", isotope.Value)
		}
	}
}
