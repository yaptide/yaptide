package process

//const (
//	maxJobDuration = 1000 * time.Second
//)
//
//type worker struct {
//	cmd                 *exec.Cmd
//	cmdString           []string
//	dirInPath           string
//	dirOutPath          string
//	workerFinishChannel chan bool
//	job                 SimulationInput
//	results             SimulationResults
//	outbuf              bytes.Buffer
//	errbuf              bytes.Buffer
//}
//
//func createWorker(job SimulationInput) (*worker, error) {
//	w := &worker{
//		job:                 job,
//		workerFinishChannel: make(chan bool),
//		results: SimulationResults{
//			Errors: map[string]string{},
//			Files:  map[string]string{},
//		},
//	}
//	setupDirectoryErr := w.setupDirectory()
//	if setupDirectoryErr != nil {
//		//job.StatusUpdate(project.Failure)
//		return nil, setupDirectoryErr
//	}
//
//	setupExecutionErr := w.setupExecution()
//	if setupExecutionErr != nil {
//		//job.StatusUpdate(project.Failure)
//		return nil, setupExecutionErr
//	}
//
//	return w, nil
//}
//
//func (w *worker) setupDirectory() error {
//	timestamp := strconv.FormatInt(time.Now().Unix(), 10)
//	w.dirInPath = path.Join(
//		"/",
//		"tmp",
//		"yaptide_tmp_simulation_files",
//		fmt.Sprintf("sim_workdir_%s_in", timestamp),
//	)
//	w.dirOutPath = path.Join(
//		"/",
//		"tmp",
//		"yaptide_tmp_simulation_files",
//		fmt.Sprintf("sim_workdir_%s_out", timestamp),
//	)
//
//	mkdirInErr := os.MkdirAll(w.dirInPath, os.ModePerm)
//	if mkdirInErr != nil {
//		log.Error("[Runner][] Unable to create workdir. Reason: %s", mkdirInErr.Error())
//		return mkdirInErr
//	}
//
//	mkdirOutErr := os.MkdirAll(w.dirOutPath, os.ModePerm)
//	if mkdirOutErr != nil {
//		log.Error("[Runner][] Unable to create workdir. Reason: %s", mkdirOutErr.Error())
//		return mkdirOutErr
//	}
//
//	for fileName, fileContent := range w.job.Files {
//		content := []byte(fileContent)
//		writeErr := ioutil.WriteFile(path.Join(w.dirInPath, fileName), content, os.ModePerm)
//		if writeErr != nil {
//			log.Error("[Runner][] Problem during file write. Reason: %s", writeErr.Error())
//			return writeErr
//		}
//	}
//	return nil
//}
//
//func (w *worker) setupExecution() error {
//	w.cmdString = w.job.CmdCreator(w.dirInPath)
//	binaryName := w.cmdString[0]
//	binaryArgs := w.cmdString[1:]
//
//	log.Debug(binaryName)
//	binaryPath, lookupErr := exec.LookPath(binaryName)
//	if lookupErr != nil {
//		log.Error("[Runner.] Unable to find %s on PATH. Reason: %s", binaryName, lookupErr.Error())
//		return lookupErr
//	}
//
//	w.cmd = exec.Command(binaryPath, binaryArgs...)
//	w.cmd.Dir = w.dirOutPath
//	w.cmd.Stdout = &w.outbuf
//	w.cmd.Stderr = &w.errbuf
//
//	return nil
//}
//
//func (w *worker) start() {
//	timer := time.AfterFunc(maxJobDuration, func() {
//		log.Warning("[Runner][] Process is running to long.")
//		killErr := w.cmd.Process.Kill()
//		if killErr != nil {
//			log.Error("[Runner][] Unable to kill process. Reason: %s", killErr.Error())
//		}
//		w.workerFinishChannel <- true
//	})
//	defer func() {
//		timer.Stop()
//		if w.cmd.ProcessState == nil || !w.cmd.ProcessState.Exited() {
//			log.Warning("[Runner][] Process should be kiled already.")
//			killErr := w.cmd.Process.Kill()
//			if killErr != nil {
//				log.Error("[Runner][] Unable to kill process. Reason: %s", killErr.Error())
//			}
//		}
//		log.Debug("[Runner][] LogStdOut %100s", w.results.LogStdOut)
//		log.Debug("[Runner][] LogStdErr %100s", w.results.LogStdErr)
//		log.Debug("[Runner][] Errors %100s", w.results.Errors)
//		w.job.ResultCallback(w.results)
//		log.Debug("[Runner][] Defer finished")
//	}()
//
//	startErr := w.cmd.Start()
//	if startErr != nil {
//		log.Error("[Runner][Loca] Unable to start process. Reason: %s", startErr.Error())
//		return
//	}
//	go func() {
//		log.Debug("[Runner][] Waiting for simultion end ...")
//		err := w.cmd.Wait()
//		if err != nil {
//			log.Warning(
//				"[Runner][] Problem during final wait. Reason: %s\n%s",
//				err.Error(),
//				spew.Sdump(""),
//			)
//			//w.job.StatusUpdate(project.Failure)
//			w.results.Errors["invalidReturnCode"] = err.Error()
//		}
//		log.Info("[Runner][] Process finished")
//		w.workerFinishChannel <- true
//	}()
//
//	<-w.workerFinishChannel
//	w.postSimulationSteps()
//}
//
//func (w *worker) postSimulationSteps() {
//	log.Debug("[Runner][] Post simulation steps")
//	files, listDirErr := ioutil.ReadDir(w.dirOutPath)
//	if listDirErr != nil {
//		log.Debug("[Runner][] Can't access directory with solutions. Reason: %s", listDirErr.Error())
//		return
//	}
//
//	w.results.LogStdOut = w.outbuf.String()
//	w.results.LogStdErr = w.errbuf.String()
//	for _, fileInfo := range files {
//		content, readFileErr := ioutil.ReadFile(path.Join(w.dirOutPath, fileInfo.Name()))
//		if readFileErr != nil {
//			log.Error("[Runner][] Can't open %s in simulation directory. Reason: %s", fileInfo.Name(), readFileErr.Error())
//			w.results.Errors["readResultFiles"] = readFileErr.Error()
//			return
//		}
//		w.results.Files[fileInfo.Name()] = string(content)
//	}
//}
