package model

// Color represent (R, G, B , A) color.
type Color struct {
	R uint8 `json:"r"`
	G uint8 `json:"g"`
	B uint8 `json:"b"`
	A uint8 `json:"a"`
}

// New construct new color.
func NewColor(R, G, B, A uint8) Color {
	return Color{R: R, G: G, B: B, A: A}
}

var (
	// White color.
	White = NewColor(0xFF, 0xFF, 0xFF, 0xFF)

	//Gray color.
	Gray = NewColor(0x80, 0x80, 0x80, 0xFF)
)
