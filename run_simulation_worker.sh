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

# simulations running before a restart are lost (the engine marks them failed), so their directories can go
rm -rf "${TMPDIR:-/tmp}"/yaptide_task_* /tmp/ray/session_*

# nproc ignores the container's CPU limit (MAX_CORES), so the limit comes first
NUM_CPUS="${RAY_NUM_CPUS:-$MAX_CORES}"
NUM_CPUS="${NUM_CPUS%.*}"
NUM_CPUS="${NUM_CPUS:-$(nproc)}"
if [ "$NUM_CPUS" -lt 1 ]; then
    NUM_CPUS=1
fi

# Ray's ports are open to every container of the project, so it always runs with a token (RAY_AUTH_MODE=token
# from compose): the one from .env, or one generated into ~/.ray/auth_token, read also by the healthcheck
if [ -z "$RAY_AUTH_TOKEN" ]; then
    ray get-auth-token --generate > /dev/null
fi

# Ray runs in the background, the engine in the foreground: when the engine stops, the container restarts
# with everything that ran on it
ray start --head --port=6379 --num-cpus="$NUM_CPUS" --object-store-memory=$((768 * 1024 * 1024)) \
    --include-dashboard=false --disable-usage-stats
# imported, not run as __main__: Ray would then send the engine's actors by value, with the database object in them
exec python -c "from yaptide.engine.engine import main; main()"
