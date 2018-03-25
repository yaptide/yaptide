package setup

import "github.com/yaptide/converter/shield/context"

// Operation decribe how to construct zone using bodies.
type Operation string

const (
	// Union represent set union.
	Union Operation = "OR"

	// Intersection represent set intersection.
	Intersection Operation = "  "
)

// Sign tells, if complement (-) is used instead of normal area (+).
type Sign string

const (
	// Plus represent normal area of body.
	Plus Sign = "+"

	// Minus represent complement of body.
	Minus Sign = "-"
)

func (s *Sign) opposite() Sign {
	if *s == Plus {
		return Minus
	}
	return Plus
}

// Construction represent steps to build zone by context.
type Construction struct {
	Operation Operation
	Sign      Sign
	BodyID    context.BodyID
}

// Zone represent zone in shield files.
type Zone struct {
	ID            context.ZoneID
	Constructions []Construction
}

// ZoneToMaterial mapping.
type ZoneToMaterial struct {
	ZoneID     context.ZoneID
	MaterialID context.MaterialID
}

func convertTreeToZones(root *zoneTree) ([]Zone, []ZoneToMaterial, error) {
	zones := []Zone{}
	zoneToMaterialPairs := []ZoneToMaterial{}

	for t := range traverseTreeUsingDFS(root) {
		tOet := oetFromZoneDescription(t.baseBodyID, t.operations)

		childrenOets := []*oet{}
		for _, children := range t.childrens {
			childrenOets = append(childrenOets,
				oetFromZoneDescription(children.baseBodyID, children.operations))
		}

		childsUnion := oetUnion(childrenOets...)

		zoneOet := oetSubtract(tOet, childsUnion)

		zones = append(zones, Zone{
			ID:            genNextZoneID(zones),
			Constructions: zoneOet.toConstructions(),
		})

		zoneToMaterialPairs = append(zoneToMaterialPairs, ZoneToMaterial{
			ZoneID:     zones[len(zones)-1].ID,
			MaterialID: t.materialID,
		})
	}

	return zones, zoneToMaterialPairs, nil
}

func genNextZoneID(zones []Zone) context.ZoneID {
	return context.ZoneID(len(zones) + 1)
}

func recursiveWalk(tree *zoneTree, ch chan *zoneTree) {
	if tree == nil {
		return
	}

	if tree.childrens != nil {
		for _, children := range tree.childrens {
			recursiveWalk(children, ch)
		}
	}
	ch <- tree
}

func traverseTreeUsingDFS(tree *zoneTree) chan *zoneTree {
	ch := make(chan *zoneTree)

	go func() {
		recursiveWalk(tree, ch)
		close(ch)
	}()

	return ch
}
