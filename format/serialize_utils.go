package format

import (
	"fmt"
	"strconv"
	"strings"
)

func FloatToFixedWidthString(n float64, w int) string {
	wStr := strconv.Itoa(w)
	s := fmt.Sprintf("%"+wStr+"."+wStr+"f", n)
	trimed := strings.TrimRight(s[:w], "0")
	return strings.Repeat(" ", w-len(trimed)) + trimed
}
