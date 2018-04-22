package mapping

import (
	"testing"

	"github.com/yaptide/yaptide/pkg/converter/setup"
)

func TestPredefinedMaterialsToShieldICRUMapping(t *testing.T) {
	for _, predefinedMaterial := range setup.PredefinedMaterials() {
		_, found := PredefinedMaterialsToShieldICRU[predefinedMaterial.Value]
		if !found {
			t.Errorf(
				"PredefinedMaterial mapping to Shield ICRU for \"%s\" not found",
				predefinedMaterial.Value,
			)
		}
	}
}

func TestIsotopeToShieldNUCLIDMapping(t *testing.T) {
	for _, isotope := range setup.Isotopes() {
		_, found := IsotopesToShieldNUCLID[isotope.Value]
		if !found {
			t.Errorf(
				"Isotope mapping to Shield NUCLID for \"%s\" not found",
				isotope.Value,
			)
		}
	}
}
