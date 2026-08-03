#!/bin/bash
set -e

docker exec yaptide_flask python3 yaptide/admin/db_manage.py add-cluster localhost -p 3022

CONTAINER_NAME="slurmctld"
SLURM_USER="devuser"
SLURM_ACCOUNT="dev_account"
CA_PUB_KEY="./slurm/ca_key/ca_key.pub"

# 1. Create OS user in slurmctld
docker exec "$CONTAINER_NAME" useradd -m -s /bin/bash "$SLURM_USER" || true

# 2. Add to Slurm accounting database
docker exec "$CONTAINER_NAME" sacctmgr -i add account name="$SLURM_ACCOUNT" description="Local Dev" Organization="Dev" || true
docker exec "$CONTAINER_NAME" sacctmgr -i add user "$SLURM_USER" account="$SLURM_ACCOUNT" adminlevel=None || true

# 3. Inject CA public key into SSHd config
docker cp "$CA_PUB_KEY" "$CONTAINER_NAME:/etc/ssh/ca.pub"
docker exec "$CONTAINER_NAME" chmod 644 /etc/ssh/ca.pub

docker exec "$CONTAINER_NAME" bash -c '
    grep -q "^TrustedUserCAKeys" /etc/ssh/sshd_config || \
    echo "TrustedUserCAKeys /etc/ssh/ca.pub" >> /etc/ssh/sshd_config
'

# Reload sshd
docker exec "$CONTAINER_NAME" service ssh reload || docker exec "$CONTAINER_NAME" systemctl reload sshd || true

# 4. SHIELDHIT Setup
echo "---> Deploying SHIELD-HIT binary and Lmod module..."
docker exec "$CONTAINER_NAME" mkdir -p /opt/spack/modules/shieldhit/bin
docker cp ./bin/shieldhit "$CONTAINER_NAME":/opt/spack/modules/shieldhit/bin/shieldhit
docker exec "$CONTAINER_NAME" chmod +x /opt/spack/modules/shieldhit/bin/shieldhit

docker exec "$CONTAINER_NAME" bash -c '
mkdir -p /opt/modulefiles/shieldhit
cat << "EOF" > /opt/modulefiles/shieldhit/default.lua
help([[
Loads the SHIELD-HIT12A Monte Carlo particle transport simulation framework.
]])

whatis("Name: SHIELD-HIT12A")
whatis("Category: Physics Simulation")

local root = "/opt/spack/modules/shieldhit"
prepend_path("PATH", pathJoin(root, "bin"))
EOF
'

echo "Slurmctld ready to accept local CA-signed SSH connections and run SHIELD-HIT."