#!/bin/bash

# check which docker version we have installed
docker_version=$(docker -v | awk '{print $3}' | cut -d, -f1)

# print the docker version
echo "Docker version: $docker_version"

# the keys of the results bucket, generated once into .env: Garage keeps them from its first start
# (https://yaptide.github.io/for_developers/backend/docker-deployment/#result-storage)
if ! grep -qs '^RESULTS_S3_ACCESS_KEY=' .env; then
  hex() { od -An -tx1 -N"$1" /dev/urandom | tr -d ' \n'; }
  if [ -s .env ] && [ -n "$(tail -c1 .env)" ]; then echo >> .env; fi
  { echo "RESULTS_S3_ACCESS_KEY=GK$(hex 12)"; echo "RESULTS_S3_SECRET_KEY=$(hex 32)"; echo "GARAGE_RPC_SECRET=$(hex 32)"; } >> .env
  echo "Generated the keys of the results bucket into .env, keep them"
fi

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
