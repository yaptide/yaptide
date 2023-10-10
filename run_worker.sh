#!/bin/bash

./yaptide/admin/simulators.py install --name shieldhit --path /simulators/shieldhit12a/bin

if [ -z "$S3_TOPAS_BUCKET" ] || [ -z "$S3_TOPAS_KEY" ] || [ -z "$S3_TOPAS_VERSION" ] || [ -z "$S3_GEANT_BUCKET" ]; then
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

        ./yaptide/admin/simulators.py install --name topas --path /simulators
fi

export LOG_LEVEL_CELERY=${LOG_LEVEL_CELERY-INFO}

celery --app yaptide.celery.worker worker -E --loglevel="$LOG_LEVEL_CELERY" -P eventlet --hostname yaptide-worker
