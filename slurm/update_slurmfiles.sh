#!/usr/bin/env bash
set -e

# Auto-detect Slurm version from .env file
if [ ! -f .env ]; then
    echo "Error: .env file not found"
    exit 1
fi

SLURM_VERSION=25.11.4

VERSION_DIR=$(echo "$SLURM_VERSION" | cut -d. -f1-2)

restart=false

for var in "$@"
do
    # Determine the source path based on filename
    case "$var" in
        slurm.conf)
            SOURCE_FILE="config/${VERSION_DIR}/slurm.conf"
            ;;
        slurmdbd.conf)
            SOURCE_FILE="config/common/slurmdbd.conf"
            ;;
        cgroup.conf)
            SOURCE_FILE="config/common/cgroup.conf"
            ;;
        *)
            echo "Warning: Unknown config file '$var', skipping"
            continue
            ;;
    esac

    # Check if source file exists
    if [ ! -f "$SOURCE_FILE" ]; then
        echo "Error: Source file '$SOURCE_FILE' not found"
        exit 1
    fi

    echo "Copying $SOURCE_FILE to container..."
    export SLURM_TMP=$(cat "$SOURCE_FILE")
    docker exec slurmctld bash -c "echo \"$SLURM_TMP\" >/etc/slurm/\"$var\""
    restart=true
done

if $restart; then
    echo "Restarting containers..."
    docker compose restart
    echo "Configuration updated successfully"
fi
