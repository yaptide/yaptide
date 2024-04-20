#!/bin/bash

# check which docker version we have installed
docker_version=$(docker -v | awk '{print $3}' | cut -d, -f1)

# print the docker version
echo "Docker version: $docker_version"

# if docker version if less than 25.0 then print a warning
if [ $(echo "$docker_version < 25.0" | bc) -eq 1 ]; then
  echo "WARNING: Docker version is less than 25.0"
fi


# build the containers
echo "Building containers"
docker compose --file docker-compose.yml --build

# try fast version, which should run on docker 25.0 and above
echo "Starting fast version"
docker compose --file docker-compose.yml --file docker-compose.fast.yml up  --detach

# if the fast version failed, try the slow version
if [ $? -ne 0 ]; then
  echo "Starting slow version"
  docker compose --file docker-compose.yml up --detach
fi
