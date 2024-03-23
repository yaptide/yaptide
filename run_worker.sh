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

celery --app yaptide.celery.worker worker --events --loglevel="$LOG_LEVEL_ROOT" --pool eventlet --hostname yaptide-worker
