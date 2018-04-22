package geometry

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/yaptide/converter"
	"github.com/yaptide/converter/geometry"
	"github.com/yaptide/converter/setup"
)

func TestSuccessfullBodiesConvert(t *testing.T) {
	type testCase struct {
		Input    converter.BodyMap
		Expected []Body
	}

	check := func(t *testing.T, tc testCase) {
		t.Helper()

		actual, _, actualErr := convertSetupBodies(tc.Input)

		assert.Equal(t, nil, actualErr)
		assert.Equal(t, tc.Expected, actual)
	}

	t.Run("Sphere", func(t *testing.T) {
		check(t, testCase{
			Input: createBodyMap(setup.Body{
				ID: 1,
				Geometry: setup.BodyGeometry{setup.SphereBody{
					Center: geometry.Point{X: 20.0, Y: 31.0, Z: 0.99},
					Radius: 0.01,
				}},
			}),
			Expected: []Body{Body{ID: 1, Identifier: "SPH", Arguments: []float64{20.0, 31.0, 0.99, 0.01}}},
		})
	})

	t.Run("Cuboid", func(t *testing.T) {
		check(t, testCase{
			Input: createBodyMap(setup.Body{
				ID: 1,
				Geometry: setup.BodyGeometry{setup.CuboidBody{
					Center: geometry.Point{X: 10.0, Y: 20.0, Z: 30.0},
					Size:   geometry.Vec3D{X: 100.0, Y: 200.0, Z: 30.5},
				}},
			}),
			Expected: []Body{Body{
				ID: 1, Identifier: "RPP",
				Arguments: []float64{-40.0, 60.0, -80.0, 120.0, 14.75, 45.25},
			}},
		})
	})

	t.Run("Cylinder", func(t *testing.T) {
		check(t, testCase{
			Input: createBodyMap(setup.Body{
				ID: 1,
				Geometry: setup.BodyGeometry{setup.CylinderBody{
					Center: geometry.Point{X: 10.1, Y: 20.2, Z: 30.3},
					Height: 24.4,
					Radius: 99.5,
				}},
			}),
			Expected: []Body{Body{
				ID: 1, Identifier: "RCC",
				Arguments: []float64{10.1, 20.2, 30.3, 0.0, 24.4, 0.0, 99.5},
			}},
		})
	})

	t.Run("ManyMixed", func(t *testing.T) {
		check(t, testCase{
			Input: createBodyMap(
				setup.Body{
					ID: 3,
					Geometry: setup.BodyGeometry{setup.CylinderBody{
						Center: geometry.Point{X: 10.1, Y: 20.2, Z: 30.3},
						Height: 24.4,
						Radius: 99.5,
					}},
				},
				setup.Body{
					ID: 4,
					Geometry: setup.BodyGeometry{setup.SphereBody{
						Center: geometry.Point{X: 20.0, Y: 31.0, Z: 0.99},
						Radius: 0.01,
					}},
				},
				setup.Body{
					ID: 1,
					Geometry: setup.BodyGeometry{setup.CylinderBody{
						Center: geometry.Point{X: 0.0, Y: 1.0, Z: 2.0},
						Height: 3.0,
						Radius: 4.0,
					}},
				},
				setup.Body{
					ID: 2,
					Geometry: setup.BodyGeometry{setup.CuboidBody{
						Center: geometry.Point{X: 10.0, Y: 20.0, Z: 30.0},
						Size:   geometry.Vec3D{X: 100.0, Y: 200.0, Z: 30.5},
					}},
				},
			),
			Expected: []Body{
				Body{ID: 1, Identifier: "RCC", Arguments: []float64{0.0, 1.0, 2.0, 0.0, 3.0, 0.0, 4.0}},
				Body{ID: 2, Identifier: "RPP", Arguments: []float64{-40.0, 60.0, -80.0, 120, 14.75, 45.25}},
				Body{ID: 3, Identifier: "RCC", Arguments: []float64{10.1, 20.2, 30.3, 0.0, 24.4, 0.0, 99.5}},
				Body{ID: 4, Identifier: "SPH", Arguments: []float64{20.0, 31.0, 0.99, 0.01}},
			},
		},
		)
	})
}

func TestAppendBlackholeBody(t *testing.T) {

	inputBodies := []Body{
		Body{ID: 1, Identifier: "RCC", Arguments: []float64{0.0, 1.0, 2.0, 0.0, 3.0, 0.0, 4.0}},
		Body{ID: 2, Identifier: "RPP", Arguments: []float64{-40.0, 60.0, -80.0, 120, 14.75, 45.25}},
		Body{ID: 3, Identifier: "RCC", Arguments: []float64{10.1, 20.2, 30.3, 0.0, 24.4, 0.0, 99.5}},
		Body{ID: 4, Identifier: "SPH", Arguments: []float64{20.0, 31.0, 0.99, 0.01}}}

	const expectedBlackholeBodyID ShieldBodyID = 5

	expectedBodiesAfterAppend := []Body{
		Body{ID: 1, Identifier: "RCC",
			Arguments: []float64{0.0, 1.0, 2.0, 0.0, 3.0, 0.0, 4.0},
		},
		Body{ID: 2, Identifier: "RPP",
			Arguments: []float64{-40.0, 60.0, -80.0, 120, 14.75, 45.25},
		},
		Body{ID: 3, Identifier: "RCC",
			Arguments: []float64{10.1, 20.2, 30.3, 0.0, 24.4, 0.0, 99.5},
		},
		Body{ID: 4, Identifier: "SPH",
			Arguments: []float64{20.0, 31.0, 0.99, 0.01},
		},
		Body{ID: expectedBlackholeBodyID, Identifier: "RPP",
			Arguments: []float64{-250.0, 250.0, -250.0, 250.0, -250.0, 250.0},
		}}

	bodiesAfterAppend, blackholeBodyID, err := appendBlackholeBody(inputBodies)

	assert.Equal(t, nil, err)
	assert.Equal(t, expectedBodiesAfterAppend, bodiesAfterAppend)
	assert.Equal(t, expectedBlackholeBodyID, blackholeBodyID)
}

func createBodyMap(bodies ...setup.Body) converter.BodyMap {
	res := converter.BodyMap{}
	for _, b := range bodies {
		res[b.ID] = b
	}
	return res
}
