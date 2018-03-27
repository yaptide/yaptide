package main

import (
	"fmt"
	"net/url"
	"os"
	"os/signal"
	"time"

	"github.com/gorilla/websocket"
	log "github.com/sirupsen/logrus"
	"github.com/yaptide/worker/config"
	"github.com/yaptide/worker/protocol"
	"github.com/yaptide/worker/simulation"
)

func connectAndServe(config config.Config, simRunner simulation.Runner) error {

	conn := connect(config.Address, protocol.YaptideListenPath)
	defer conn.Close()

	isValidToken, err := helloMessageHandshake(conn, config.Token, simRunner)

	switch {
	case err != nil:
		return err
	case !isValidToken:
		return fmt.Errorf("Token authentication failed")
	}

	go waitForInterrupt(conn)

	messageReadLoop(conn, simRunner)

	return nil
}

func connect(address, path string) *websocket.Conn {
	url := url.URL{Scheme: "ws", Host: address, Path: path}

	for {
		log.Infof("Connecting to %s", address)

		conn, _, err := websocket.DefaultDialer.Dial(url.String(), nil)
		if err != nil {
			log.Error(err.Error())
			time.Sleep(1 * time.Second)
		} else {
			return conn
		}
	}
}

func helloMessageHandshake(conn *websocket.Conn, token string, simRunner simulation.Runner) (bool, error) {
	err := conn.WriteJSON(
		protocol.HelloRequestMessage{
			Token: token,
			AvailableComputingLibrariesNames: simRunner.AvailableComputingLibrariesNames(),
		},
	)
	if err != nil {
		return false, err
	}

	var helloResponseMessage protocol.HelloResponseMessage
	err = conn.ReadJSON(&helloResponseMessage)
	if err != nil {
		return false, nil
	}

	return helloResponseMessage.TokenValid, nil
}

func messageReadLoop(conn *websocket.Conn, simRunner simulation.Runner) {
	for {
		var runSimulationMessage protocol.RunSimulationMessage
		err := conn.ReadJSON(&runSimulationMessage)
		if err != nil {
			log.Warn("read:", err)
			continue
		}

		resultFiles, errors := simRunner.Run(runSimulationMessage.ComputingLibraryName, runSimulationMessage.Files)

		err = conn.WriteJSON(protocol.SimulationResultsMessage{
			Files:  resultFiles,
			Errors: errors,
		})

		if err != nil {
			log.Warn("write:", err)
			continue
		}

	}
}

func waitForInterrupt(conn *websocket.Conn) error {
	interrupt := make(chan os.Signal)
	signal.Notify(interrupt, os.Interrupt)
	for {
		select {
		case <-interrupt:
			log.Info("interrupt")
			err := conn.WriteMessage(websocket.CloseMessage, websocket.FormatCloseMessage(websocket.CloseNormalClosure, ""))
			if err != nil {
				return err
			}
			time.Sleep(2 * time.Second)
			return nil
		}
	}
}
