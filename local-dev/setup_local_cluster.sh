#!/bin/bash
# Registers the local SLURM container as a batch cluster in the yaptide database.
#
# Run this ONCE after the stack is up:
#   bash local-dev/setup_local_cluster.sh
#
# The cluster_name "slurm" must match:
#   - the Docker service hostname (hostname: slurm in docker-compose-local-slurm.yml)
#   - SlurmctldHost / NodeName in local-dev/slurm/slurm.conf
#
# batch_methods.get_connection() connects via:
#   Connection(host=f"{user.username}@{cluster.cluster_name}")
# → connects to SSH on container "slurm" within the Docker network.

set -euo pipefail

FLASK_CONTAINER="yaptide_flask"
CLUSTER_NAME="slurm"

echo "Registering cluster '${CLUSTER_NAME}' in the database..."
docker exec "${FLASK_CONTAINER}" \
    python3 yaptide/admin/db_manage.py add-cluster "${CLUSTER_NAME}"

echo ""
echo "Registered clusters:"
docker exec "${FLASK_CONTAINER}" \
    python3 yaptide/admin/db_manage.py list-clusters
