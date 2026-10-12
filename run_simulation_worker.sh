#!/bin/bash

./yaptide/admin/simulators.py download-shieldhit --dir /simulators/shieldhit12a/bin --decrypt

if [ -z "$S3_TOPAS_BUCKET" ] || [ -z "$S3_TOPAS_KEY" ] || [ -z "$S3_TOPAS_VERSION" ] || [ -z "$S3_GEANT4_BUCKET" ]; then
        echo "One or more environment variables required by TOPAS are not set, skipping TOPAS installation"
    else
        apt-get update

        apt-get install -y --no-install-recommends \
        libexpat1-dev \
        libgl1-mesa-dev \
        libglu1-mesa-dev \
        libxt-dev \
        xorg-dev \
        build-essential \
        libharfbuzz-dev \
        gfortran

        rm -rf /var/lib/apt/lists/*

        ./yaptide/admin/simulators.py download-topas --dir /simulators
fi


if [ -z "$S3_FLUKA_BUCKET" ] || [ -z "$S3_FLUKA_KEY" ]; then
    echo "One or more environment variables required by FLUKA are not set, skipping FLUKA installation"
else
    ./yaptide/admin/simulators.py download-fluka --dir /simulators
fi

# simulations running before a restart are lost, so the working directories they left can go
rm -rf "${TMPDIR:-/tmp}"/yaptide_task_*

NUM_CPUS="${RAY_NUM_CPUS%.*}"
NUM_CPUS="${NUM_CPUS:-$(nproc)}"
if [ "$NUM_CPUS" -lt 1 ]; then
    NUM_CPUS=1
fi

# without GRPC_ENABLE_FORK_SUPPORT=0 the Ray client server crashes when a Flask worker connects
GRPC_ENABLE_FORK_SUPPORT=0 exec ray start --head --port=6379 --ray-client-server-port=10001 \
    --num-cpus="$NUM_CPUS" --object-store-memory=$((768 * 1024 * 1024)) \
    --include-dashboard=false --disable-usage-stats --block
