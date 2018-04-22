#!/usr/bin/env bash

set -x

function ensure_line() {
    grep -Fxq "$1" "$2"
    RETURN_CODE=$?
    if [[ "$RETURN_CODE" != "0" ]]; then
        echo "$1" >> "$2"
    fi
}

BASHRC_PATH="$HOME/.bashrc"
ZSHRC_PATH="$HOME/.zshrc"

GO_BINNARY_PATH=$(command -v go)
if [[ -z $GO_BINNARY_PATH ]]; then
    sudo apt-get -y install wget
    wget https://dl.google.com/go/go1.9.2.linux-amd64.tar.gz
    tar -xf go1.9.2.linux-amd64.tar.gz
    sudo mkdir -p /opt
    sudo mv go /opt/go
    rm go1.9.2.linux-amd64.tar.gz

    
    GOROOT_EXPORT='export GOROOT="/opt/go"'
    ensure_line "$GOROOT_EXPORT" "$ZSHRC_PATH"
    ensure_line "$GOROOT_EXPORT" "$BASHRC_PATH"
    export GOROOT="/opt/go"
    
    GOROOT_PATH_EXPORT='export PATH="/opt/go/bin:$PATH"'
    ensure_line "$GOROOT_PATH_EXPORT" "$ZSHRC_PATH"
    ensure_line "$GOROOT_PATH_EXPORT" "$BASHRC_PATH"
    export PATH="/opt/go/bin:$PATH"
fi

if [[ -z $GOPATH ]]; then
    mkdir -p $HOME/go
    GOPATH_EXPORT='export GOPATH="$HOME/go"'
    GOPATH_PATH_EXPORT='export PATH="$HOME/go/bin:$PATH"'
    ensure_line "$GOPATH_EXPORT" "$ZSHRC_PATH"
    ensure_line "$GOPATH_EXPORT" "$BASHRC_PATH"
    ensure_line "$GOPATH_PATH_EXPORT" "$ZSHRC_PATH"
    ensure_line "$GOPATH_PATH_EXPORT" "$BASHRC_PATH"

    export GOPATH="$HOME/go"
    export PATH="$HOME/go/bin:$PATH"
fi

go get github.com/yaptide/builder
go get github.com/yaptide/yaptide
go get github.com/yaptide/ui
go get github.com/yaptide/yaptide/pkg/converter

set -e

cd $GOPATH/src/github.com/yaptide/builder
go get -u github.com/golang/dep/cmd/dep
dep ensure
go run launch/main.go setup

