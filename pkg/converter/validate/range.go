package validate

import "math"

const floatingPointTolerance = 0.000001

// InRange ...
func InRange(start float64, end float64, value float64) bool {
	return value >= start && value <= end
}

// InRange2PI ...
func InRange2PI(value float64) bool {
	return value >= 0 && value <= math.Pi*2+floatingPointTolerance
}

// InRangePI ...
func InRangePI(value float64) bool {
	return value >= 0 && value <= math.Pi+floatingPointTolerance
}
