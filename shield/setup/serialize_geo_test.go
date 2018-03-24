package setup

import (
	"fmt"
	"strconv"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/yaptide/converter/shield"
)

func genZoneToMaterials(n int) []ZoneToMaterial {
	res := []ZoneToMaterial{}
	for i := 0; i < n; i++ {
		res = append(res, ZoneToMaterial{
			ZoneID:     shield.ZoneID(i),
			MaterialID: shield.MaterialID(i),
		})
	}
	return res
}

const geoTc1Expected = `    0    0          xxxxxxxxxxxxxxxxxxxxxxxxxxxxNAMExxxxxxxxxxxxxxxxxxxxxxxxxxxx
  RCC    1        0.        1.        2.        0.        3.        0.
                  4.                                                  
  RPP    2      -40.       60.      -80.      120.     14.75     45.25
  RCC    3      10.1      20.2      30.3        0.      24.4        0.
             99999.5                                                  
  SPH    4       20.       31.      0.99      0.01                    
  END
  AAA    1     +1     +3     -4OR   +2     +3     -4
  BAA    2     +5OR   +6
  CAA    3     +7     -8     -1     -2     -5     -6OR   +7     -8     -3
         3     -5     -6OR   +7     -8     +4     -5     -6
  END
    0    1    2    3    4    5    6    7    8    9   10   11   12   13
   14   15   16   17   18   19
    0    1    2    3    4    5    6    7    8    9   10   11   12   13
   14   15   16   17   18   19
`

func TestSerializeGeo(t *testing.T) {
	type testCase struct {
		Input    Geometry
		Expected string
	}

	testCases := []testCase{
		testCase{
			Input: Geometry{
				Bodies: []Body{
					Body{ID: 1, Identifier: "RCC", Arguments: []float64{0.0, 1.0, 2.0, 0.0, 3.0, 0.0, 4.0}},
					Body{ID: 2, Identifier: "RPP", Arguments: []float64{-40.0, 60.0, -80.0, 120, 14.75, 45.25}},
					Body{ID: 3, Identifier: "RCC", Arguments: []float64{10.1, 20.2, 30.3, 0.0, 24.4, 0.0, 99999.5}},
					Body{ID: 4, Identifier: "SPH", Arguments: []float64{20.0, 31.0, 0.99, 0.01}},
				},

				Zones: []Zone{
					Zone{
						ID: 1,
						Constructions: []Construction{
							Construction{Operation: Intersection, Sign: Plus, BodyID: 1},
							Construction{Operation: Intersection, Sign: Plus, BodyID: 3},
							Construction{Operation: Intersection, Sign: Minus, BodyID: 4},
							Construction{Operation: Union, Sign: Plus, BodyID: 2},
							Construction{Operation: Intersection, Sign: Plus, BodyID: 3},
							Construction{Operation: Intersection, Sign: Minus, BodyID: 4},
						},
					},
					Zone{
						ID: 2,
						Constructions: []Construction{
							Construction{Operation: Intersection, Sign: Plus, BodyID: 5},
							Construction{Operation: Union, Sign: Plus, BodyID: 6},
						},
					},
					Zone{
						ID: 3,
						Constructions: []Construction{
							Construction{Operation: Intersection, Sign: Plus, BodyID: 7},
							Construction{Operation: Intersection, Sign: Minus, BodyID: 8},
							Construction{Operation: Intersection, Sign: Minus, BodyID: 1},
							Construction{Operation: Intersection, Sign: Minus, BodyID: 2},
							Construction{Operation: Intersection, Sign: Minus, BodyID: 5},
							Construction{Operation: Intersection, Sign: Minus, BodyID: 6},

							Construction{Operation: Union, Sign: Plus, BodyID: 7},
							Construction{Operation: Intersection, Sign: Minus, BodyID: 8},
							Construction{Operation: Intersection, Sign: Minus, BodyID: 3},
							Construction{Operation: Intersection, Sign: Minus, BodyID: 5},
							Construction{Operation: Intersection, Sign: Minus, BodyID: 6},

							Construction{Operation: Union, Sign: Plus, BodyID: 7},
							Construction{Operation: Intersection, Sign: Minus, BodyID: 8},
							Construction{Operation: Intersection, Sign: Plus, BodyID: 4},
							Construction{Operation: Intersection, Sign: Minus, BodyID: 5},
							Construction{Operation: Intersection, Sign: Minus, BodyID: 6},
						},
					},
				},
				ZoneToMaterialPairs: genZoneToMaterials(20),
			},
			Expected: geoTc1Expected,
		},
	}

	for n, tc := range testCases {
		t.Run(strconv.Itoa(n), func(t *testing.T) {
			actual := serializeGeo(tc.Input)
			fmt.Println(actual)
			assert.Equal(t, tc.Expected, actual)
		})
	}

}
