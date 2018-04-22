// Package wsclient implement websocket worker client which exchanges messages with yaptide backend.
//
package wsclient

import (
	"fmt"
	"net/url"
	"os"
	"os/signal"
	"time"

	"github.com/gorilla/websocket"
	log "github.com/sirupsen/logrus"
	"github.com/yaptide/yaptide/worker/config"
	"github.com/yaptide/yaptide/worker/protocol"
	"github.com/yaptide/yaptide/worker/simulation"
)

// ConnectAndServe connect to yaptide backend by webscocket protocol,
// then waits for simulation RunSimulationMessages from yaptide backend.
// It use JSON messages from github.com/yaptide/yaptide/worker/protocol as protocol.
func ConnectAndServe(config config.Config, simulationRunner simulation.Runner) error {
	conn := connect(config.Address, protocol.YaptideListenPath)
	defer conn.Close()

	isValidToken, err := helloMessageHandshake(conn, config.Token, simulationRunner)

	switch {
	case err != nil:
		return err
	case !isValidToken:
		return fmt.Errorf("%s", "token authentication failed")
	}

	log.Info("token authentication succeeded")

	go closeConnectionOnInterruptSignal(conn)

	log.Info("waiting for run simulation messages...")
	messageReadLoop(conn, simulationRunner)

	return nil
}

func connect(address, path string) *websocket.Conn {
	url := url.URL{Scheme: "ws", Host: address, Path: path}

	for {
		log.Infof("connecting to %s", url.String())

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

func messageReadLoop(conn *websocket.Conn, simulationRunner simulation.Runner) {
	for {
		var runSimulationMessage protocol.RunSimulationMessage
		err := conn.ReadJSON(&runSimulationMessage)
		if err != nil {
			if websocket.IsCloseError(err, websocket.CloseNormalClosure) {
				return
			}
			log.Warn("read:", err)
			continue
		}

		resultFiles, errors := simulationRunner.Run(
			runSimulationMessage.ComputingLibraryName,
			runSimulationMessage.Files,
		)

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

func closeConnectionOnInterruptSignal(conn *websocket.Conn) {
	interrupt := make(chan os.Signal)
	signal.Notify(interrupt, os.Interrupt)

	<-interrupt
	log.Info("interrupt")
	conn.WriteMessage(
		websocket.CloseMessage,
		websocket.FormatCloseMessage(websocket.CloseNormalClosure, ""),
	)
	time.Sleep(2 * time.Second)
}
