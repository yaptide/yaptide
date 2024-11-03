#!/bin/bash

# check which docker version we have installed
docker_version=$(docker -v | awk '{print $3}' | cut -d, -f1)

# print the docker version
echo "Docker version: $docker_version"

# build the containers
echo "Building containers:"
docker compose --file docker-compose.yml build

# try fast version, which should run on docker 25.0 and above
echo "Trying to bring up containers with fast version of the command:"
docker compose --file docker-compose.yml --file docker-compose-develop.yml --file docker-compose.fast.yml up  --detach

# if the fast version failed, try the slow version
if [ $? -ne 0 ]; then
  echo "Fast version failed, trying slow version:"
  docker compose --file docker-compose.yml up --file docker-compose-develop.yml --detach
fi
