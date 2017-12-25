package config

import (
	"errors"
	"net"
	"strconv"
)

type checkFunc func(conf *Config) error

func checkConfig(conf *Config) error {
	checkFuncs := []checkFunc{
		checkPort,
	}

	for _, checkFunc := range checkFuncs {
		if err := checkFunc(conf); err != nil {
			return err
		}
	}

	return nil
}

func checkPort(conf *Config) error {
	port := conf.Port
	if port < 1000 || port > 65535 {
		return errors.New("Invalid port number")
	}

	ln, connectErr := net.Listen("tcp", ":"+strconv.FormatInt(port, 10))
	if connectErr != nil {
		return connectErr
	}
	closeErr := ln.Close()
	return closeErr
}
