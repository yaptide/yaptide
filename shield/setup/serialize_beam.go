package setup

import (
	"bytes"
	"fmt"
	"strings"

	"github.com/yaptide/converter/common"
	"github.com/yaptide/converter/log"
	"github.com/yaptide/converter/setup"
)

type beamCardSerializerFunc func(setup.Beam, setup.SimulationOptions) string

var beamCardSerializers = map[string]beamCardSerializerFunc{
	"APCORR": func(beam setup.Beam, options setup.SimulationOptions) string {
		if options.AntyparticleCorrectionOn {
			return fmt.Sprintf("%8d", 1)
		}
		return fmt.Sprintf("%8d", 0)
	},
	"BEAMDIR": func(beam setup.Beam, options setup.SimulationOptions) string {
		return floatToFixedWidthString(beam.Direction.Theta, 8) + floatToFixedWidthString(beam.Direction.Phi, 8)
	},
	"BEAMDIV": func(beam setup.Beam, options setup.SimulationOptions) string {
		return ""
	},
	"BEAMPOS": func(beam setup.Beam, options setup.SimulationOptions) string {
		return floatToFixedWidthString(beam.Direction.Position.X, 8) +
			floatToFixedWidthString(beam.Direction.Position.Y, 8) +
			floatToFixedWidthString(beam.Direction.Position.Z, 8)
	},
	"BEAMSIGMA": func(beam setup.Beam, options setup.SimulationOptions) string {
		return floatToFixedWidthString(beam.Divergence.SigmaX, 8) +
			floatToFixedWidthString(beam.Divergence.SigmaY, 8)
	},
	"BMODMC": func(beam setup.Beam, options setup.SimulationOptions) string {
		return ""
	},
	"BMODTRANS": func(beam setup.Beam, options setup.SimulationOptions) string {
		return ""
	},
	"DELTAE": func(beam setup.Beam, options setup.SimulationOptions) string {
		return floatToFixedWidthString(float64(options.MeanEnergyLoss/100), 8)
	},
	"DEMIN": func(beam setup.Beam, options setup.SimulationOptions) string {
		return floatToFixedWidthString(options.MinEnergyLoss, 8)
	},
	"EMTRANS": func(beam setup.Beam, options setup.SimulationOptions) string {
		return ""
	},
	"EXTSPEC": func(beam setup.Beam, options setup.SimulationOptions) string {
		return ""
	},
	"HIPROJ": func(beam setup.Beam, options setup.SimulationOptions) string {
		particle, ok := beam.ParticleType.(common.HeavyIon)
		if ok {
			return fmt.Sprintf("%8d", particle.NucleonsCount) + fmt.Sprintf("%8d", particle.Charge)
		}
		return ""
	},
	"JPART0": func(beam setup.Beam, options setup.SimulationOptions) string {
		number, _ := MapParticleToShieldParticleID(beam.ParticleType)
		return fmt.Sprintf("%8d", number)
	},
	"MAKELN": func(beam setup.Beam, options setup.SimulationOptions) string {
		return ""
	},
	"MSCAT": func(beam setup.Beam, options setup.SimulationOptions) string {
		if options.ScatteringType == setup.MoliereScattering {
			return fmt.Sprintf("%8d", 2)
		}
		return fmt.Sprintf("%8d", 1)
	},
	"NEUTRFAST": func(beam setup.Beam, options setup.SimulationOptions) string {
		if options.FastNeutronTransportOn {
			return fmt.Sprintf("%8d", 1)
		}
		return fmt.Sprintf("%8d", 0)
	},
	"NEUTRLCUT": func(beam setup.Beam, options setup.SimulationOptions) string {
		return floatToFixedWidthString(options.LowEnergyNeutronCutOff, 8)
	},
	"NSTAT": func(beam setup.Beam, options setup.SimulationOptions) string {
		return fmt.Sprintf("%8d", options.NumberOfGeneratedParticles) +
			fmt.Sprintf("%8d", -1)
	},
	"NUCRE": func(beam setup.Beam, options setup.SimulationOptions) string {
		if options.NuclearReactionsOn {
			return fmt.Sprintf("%8d", 1)
		}
		return fmt.Sprintf("%8d", 0)
	},
	"RNDSEED": func(beam setup.Beam, options setup.SimulationOptions) string {
		return ""
	},
	"STRAGG": func(beam setup.Beam, options setup.SimulationOptions) string {
		if options.EnergyStraggling == setup.VavilovStraggling {
			return fmt.Sprintf("%8d", 2)
		}
		return fmt.Sprintf("%8d", 1)
	},
	"TMAX0": func(beam setup.Beam, options setup.SimulationOptions) string {
		return floatToFixedWidthString(beam.InitialBaseEnergy, 8) +
			floatToFixedWidthString(beam.InitialEnergySigma, 8)
	},
	"USEBMOD": func(beam setup.Beam, options setup.SimulationOptions) string {
		return ""
	},
	"USECBEAM": func(beam setup.Beam, options setup.SimulationOptions) string {
		return ""
	},
	"USEPARLEV": func(beam setup.Beam, options setup.SimulationOptions) string {
		return ""
	},
}

var beamCardOrder = []string{
	"APCORR", "BEAMDIR", "BEAMDIV", "BEAMPOS", "BEAMSIGMA", "BMODMC", "BMODTRANS",
	"DELTAE", "DEMIN", "EMTRANS", "EXTSPEC", "HIPROJ", "JPART0", "MAKELN", "MSCAT",
	"NEUTRFAST", "NEUTRLCUT", "NSTAT", "NUCRE", "RNDSEED", "STRAGG", "TMAX0", "USEBMOD",
	"USECBEAM", "USEPARLEV",
}

func serializeBeam(beam setup.Beam, options setup.SimulationOptions) string {
	writer := &bytes.Buffer{}
	log.Debug("[Serializer][beam] start")

	for _, cardName := range beamCardOrder {
		cardSerializer := beamCardSerializers[cardName]
		cardContent := cardSerializer(beam, options)
		if cardContent == "" {
			continue
		}

		log.Debug("[Serializer][beam] write card %s with content \n%s", cardName, cardContent)
		writer.Write([]byte(serializeBeamCardName(cardName)))
		writer.Write([]byte(cardContent))
		writer.Write([]byte("\n"))
	}

	return writer.String()
}

func serializeBeamCardName(name string) string {
	return (name + strings.Repeat(" ", 16))[0:16]
}
