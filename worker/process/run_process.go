package process

import (
	"bytes"
	"fmt"
	"io/ioutil"
	"os"
	"os/exec"
	"path/filepath"
	"time"

	log "github.com/sirupsen/logrus"
)

const (
	maxJobDuration = 1000 * time.Second
)

func runProcess(
	createCMD CreateCMD, inputFiles map[string]string, maxJobDuration time.Duration,
) Result {
	result := Result{Errors: []string{}}

	workingDirPath, resultsDirPath, err := setupWorkingDirectory(inputFiles)
	if err != nil {
		result.Errors = append(result.Errors, err.Error())
	}
	log.Debugf("created working dir: %s", workingDirPath)
	log.Debugf("created results dir: %s", resultsDirPath)

	cmd := createCMD.CreateCMD(workingDirPath)
	cmd.Dir = resultsDirPath
	log.Debugf("cmd to run: %s", cmd.Path)

	stdout, stderr, err := runCmdAndWaitForResults(cmd, maxJobDuration)
	result.StdOut = stdout
	result.StdErr = stderr
	if err != nil {
		err = fmt.Errorf("run %s error: %s", cmd.Path, err)
		log.Errorf(err.Error())
		result.Errors = append(result.Errors, err.Error())
		return result
	}

	resultFiles, err := gatherResultsFiles(resultsDirPath)
	if err != nil {
		result.Errors = append(result.Errors, err.Error())
		return result
	}
	result.Files = resultFiles

	removeWorkingDir(workingDirPath)

	return result
}

func setupWorkingDirectory(
	inputFiles map[string]string,
) (workingDirPath string, resultsDirPath string, err error) {
	workingDirPath, err = ioutil.TempDir("", "yaptide-worker-working-dir-")
	if err != nil {
		return "", "", fmt.Errorf("working dir creation error: %s", err.Error())
	}

	permissions := os.FileMode(0700)

	for fileName, fileContent := range inputFiles {
		writeErr := ioutil.WriteFile(
			filepath.Join(workingDirPath, fileName),
			[]byte(fileContent),
			permissions,
		)

		if writeErr != nil {
			return "", "", fmt.Errorf("write to %s file error: %s", fileName, writeErr.Error())
		}
	}

	resultsDirPath = filepath.Join(workingDirPath, "results")
	err = os.Mkdir(resultsDirPath, permissions)
	if err != nil {
		return "", "", fmt.Errorf("results dir in working dir creation error: %s", err.Error())
	}
	return workingDirPath, resultsDirPath, err
}

func runCmdAndWaitForResults(
	cmd *exec.Cmd, maxJobDuration time.Duration,
) (stdout string, stderr string, err error) {
	processFinished := make(chan error)

	stdoutBuff := &bytes.Buffer{}
	stderrBuff := &bytes.Buffer{}
	cmd.Stdout = stdoutBuff
	cmd.Stderr = stderrBuff

	err = cmd.Start()
	if err != nil {
		return "", "", err
	}

	go func() {
		processFinished <- cmd.Wait()
	}()

	select {
	case err = <-processFinished:
	case <-time.After(maxJobDuration):
		err = fmt.Errorf("%s command timeout expired", cmd.Path)
		_ = cmd.Process.Kill()
	}

	stdout = stdoutBuff.String()
	stderr = stderrBuff.String()
	return stdout, stderr, err
}

func removeWorkingDir(workingDirPath string) {
	err := os.RemoveAll(workingDirPath)
	if err != nil {
		log.Debugf("remove working dir %s error: %s", workingDirPath, err.Error())
	} else {
		log.Debugf("removed working dir %s", workingDirPath)
	}
}

func gatherResultsFiles(workingDirPath string) (map[string]string, error) {
	resultFiles := map[string]string{}

	files, err := ioutil.ReadDir(workingDirPath)
	if err != nil {
		return nil, fmt.Errorf("can not read files list: %s", err.Error())
	}

	for _, f := range files {
		path := filepath.Join(workingDirPath, f.Name())
		if f.IsDir() {
			continue
		}
		content, err := ioutil.ReadFile(path)
		if err != nil {
			return nil, err
		}

		resultFiles[f.Name()] = string(content)
	}

	return resultFiles, nil
}
