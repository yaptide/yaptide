// +build linux

package process

import (
	"fmt"
	"os/exec"
	"path/filepath"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
)

type CreateCatCMD struct {
}

func (c *CreateCatCMD) CreateCMD(workingDirPath string) *exec.Cmd {
	toRun := fmt.Sprintf("cat %s | tee ala_result", filepath.Join(workingDirPath, "ala"))
	cmd := exec.Command("bash", "-c", toRun)
	cmd.Dir = workingDirPath
	return cmd
}

type CreateInfiniteSleepCMD struct {
}

func (c *CreateInfiniteSleepCMD) CreateCMD(workingDirPath string) *exec.Cmd {
	cmd := exec.Command("sleep", "1h")
	cmd.Dir = workingDirPath
	return cmd
}

func TestRunProcess(t *testing.T) {
	t.Run("Successful Run", func(t *testing.T) {
		result := runProcess(&CreateCatCMD{}, map[string]string{"ala": "ma_psa"}, time.Hour)
		assert.Equal(t,
			Result{
				Files: map[string]string{
					"ala_result": "ma_psa",
				},
				StdOut: "ma_psa",
				StdErr: "",
				Errors: []string{},
			},
			result,
		)
	})

	t.Run("Timeout", func(t *testing.T) {
		result := runProcess(&CreateInfiniteSleepCMD{}, map[string]string{}, time.Millisecond)
		assert.Equal(t, 1, len(result.Errors))
	})
}
