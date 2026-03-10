#!/bin/bash
# Registers the local SLURM container as a batch cluster in the yaptide database.
#
# Run this ONCE after the stack is up:
#   bash local-dev/setup_local_cluster.sh
#
# In the default all-Docker mode, db_manage.py runs inside the yaptide_flask container.
# In external-Flask mode (Flask running locally via Poetry), pass --external-flask.
# NOTE: Flask must already be running (Step D) before calling this, because Flask
# creates the database tables on startup via create_all().
#   bash local-dev/setup_local_cluster.sh --external-flask
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
EXTERNAL_FLASK=false

for arg in "$@"; do
  [[ "$arg" == "--external-flask" ]] && EXTERNAL_FLASK=true
done

if [[ "$EXTERNAL_FLASK" == true ]]; then
  DB_URI="${FLASK_SQLALCHEMY_DATABASE_URI:-postgresql+psycopg://yaptide_user:yaptide_password@localhost:5432/yaptide_db}"
  echo "Registering cluster '${CLUSTER_NAME}' via Poetry (external-Flask mode)..."
  echo "(Flask must already be running so that database tables exist)"
  FLASK_SQLALCHEMY_DATABASE_URI="$DB_URI" \
    poetry -C "$(dirname "$0")/.." run python yaptide/admin/db_manage.py add-cluster "${CLUSTER_NAME}"
  echo ""
  echo "Registered clusters:"
  FLASK_SQLALCHEMY_DATABASE_URI="$DB_URI" \
    poetry -C "$(dirname "$0")/.." run python yaptide/admin/db_manage.py list-clusters
else
  echo "Registering cluster '${CLUSTER_NAME}' in the database..."
  docker exec "${FLASK_CONTAINER}" \
      python3 yaptide/admin/db_manage.py add-cluster "${CLUSTER_NAME}"
  echo ""
  echo "Registered clusters:"
  docker exec "${FLASK_CONTAINER}" \
      python3 yaptide/admin/db_manage.py list-clusters
fi
