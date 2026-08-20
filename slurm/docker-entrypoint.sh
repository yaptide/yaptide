#!/bin/bash
set -e

# --- SCRATCH Directory Setup ---
mkdir -p /tmp/scratch
chmod 1777 /tmp/scratch

# 1. For Login Shells (/etc/profile.d/)
cat << 'EOF' > /etc/profile.d/scratch.sh
export SCRATCH="/tmp/scratch/${USER:-devuser}"
if [ ! -d "$SCRATCH" ]; then
    mkdir -p "$SCRATCH" 2>/dev/null
fi
EOF
chmod +x /etc/profile.d/scratch.sh

# 2. For Non-Login SSH Shells used by Fabric (/etc/bashrc)
if ! grep -q 'export SCRATCH=' /etc/bashrc; then
    cat << 'EOF' >> /etc/bashrc

# Ensure SCRATCH is set for non-interactive SSH sessions
export SCRATCH="/tmp/scratch/${USER:-devuser}"
if [ ! -d "$SCRATCH" ]; then
    mkdir -p "$SCRATCH" 2>/dev/null
fi
EOF
fi

# Detect replica number by matching own IP against Docker Compose DNS entries.
# Compose names containers as <project>-<service>-<N>, and Docker's embedded DNS
# resolves these names within the network. We iterate N=1..max and find which
# one resolves to our IP.
# Falls back to the container ID (hostname) if detection fails.
detect_replica_number() {
    local service_name="$1"
    local max_replicas="${2:-64}"
    local my_ip
    my_ip=$(hostname -i 2>/dev/null | awk '{print $1}')

    for i in $(seq 1 "$max_replicas"); do
        local resolved=""

        # Try <project>-<service>-<N>
        if [ -n "${COMPOSE_PROJECT_NAME}" ]; then
            resolved=$(getent hosts "${COMPOSE_PROJECT_NAME}-${service_name}-${i}" 2>/dev/null | awk '{print $1}')
        fi

        # Fallback to <service>-<N>
        if [ -z "$resolved" ]; then
            resolved=$(getent hosts "${service_name}-${i}" 2>/dev/null | awk '{print $1}')
        fi

        if [ "$resolved" = "$my_ip" ]; then
            echo "$i"
            return 0
        fi
    done

    # Fallback if replica number cannot be determined from DNS
    echo "1"
    return 0
}

echo "---> Starting the MUNGE Authentication service (munged) ..."
gosu munge /usr/sbin/munged

SLURM_USER="${SLURM_USER:-devuser}"
if ! id "$SLURM_USER" &>/dev/null; then
    echo "---> Creating OS user: $SLURM_USER"
    useradd -m -s /bin/bash "$SLURM_USER"
fi

if [ "$1" = "slurmdbd" ]
then
    echo "---> Starting the Slurm Database Daemon (slurmdbd) ..."

    # Substitute environment variables in slurmdbd.conf
    envsubst < /etc/slurm/slurmdbd.conf > /etc/slurm/slurmdbd.conf.tmp
    mv /etc/slurm/slurmdbd.conf.tmp /etc/slurm/slurmdbd.conf
    chown slurm:slurm /etc/slurm/slurmdbd.conf
    chmod 600 /etc/slurm/slurmdbd.conf

    # create jwt key for jwt/auth
    if [ ! -f /etc/slurm/jwt_hs256.key ]; then
        dd if=/dev/random of=/etc/slurm/jwt_hs256.key bs=32 count=1
        chown slurm:slurm /etc/slurm/jwt_hs256.key
        chmod 0600 /etc/slurm/jwt_hs256.key
    fi

    # Wait for MySQL using environment variables directly
    until echo "SELECT 1" | mysql -h mysql -uslurm -ppassword 2>&1 > /dev/null
    do
        echo "-- Waiting for database to become active ..."
        sleep 2
    done
    echo "-- Database is now active ..."

    exec gosu slurm /usr/sbin/slurmdbd -Dvvv
    # exec tail -f /dev/null
fi

if [ "$1" = "slurmctld" ]
then
    if [ "$SSH_ENABLE" = "true" ]; then
        echo "---> Configuring SSH ..."

        if [ -f /tmp/ca.pub ]; then
            cp /tmp/ca.pub /etc/ssh/ca.pub
            chown root:root /etc/ssh/ca.pub
            chmod 644 /etc/ssh/ca.pub
            grep -q '^TrustedUserCAKeys' /etc/ssh/sshd_config || echo 'TrustedUserCAKeys /etc/ssh/ca.pub' >> /etc/ssh/sshd_config
            grep -q '^PubkeyAcceptedAlgorithms' /etc/ssh/sshd_config || echo 'PubkeyAcceptedAlgorithms +rsa-sha2-512-cert-v01@openssh.com,rsa-sha2-256-cert-v01@openssh.com' >> /etc/ssh/sshd_config
        fi

        if [ -s /tmp/authorized_keys_host ]; then
            mkdir -p /root/.ssh
            cp /tmp/authorized_keys_host /root/.ssh/authorized_keys
            chown root:root /root/.ssh/authorized_keys
            chmod 600 /root/.ssh/authorized_keys
            chown root:root /root/.ssh
            chmod 700 /root/.ssh
            echo "---> Copied and set permissions for authorized_keys"
        fi

        echo "---> Starting SSHD ..."
        /usr/sbin/sshd
    fi

    echo "---> Waiting for slurmdbd to become active before starting slurmctld ..."
    until 2>/dev/null >/dev/tcp/slurmdbd/6819
    do
        echo "-- slurmdbd is not available.  Sleeping ..."
        sleep 2
    done
    echo "-- slurmdbd is now active ..."

    # --- Slurm Accounting Setup ---
    SLURM_ACCOUNT="${SLURM_ACCOUNT:-dev_account}"
    echo "---> Provisioning Slurm accounts and users in sacctmgr..."
    sacctmgr -i add account name="$SLURM_ACCOUNT" description="Local Dev" Organization="Dev" || true
    sacctmgr -i add user "$SLURM_USER" account="$SLURM_ACCOUNT" adminlevel=None || true

    # --- SHIELD-HIT Lmod Module Setup ---
    echo "---> Provisioning SHIELD-HIT Lmod module..."
    mkdir -p /opt/modulefiles/shieldhit
    cat << 'EOF' > /opt/modulefiles/shieldhit/default.lua
help([[
Loads the SHIELD-HIT12A Monte Carlo particle transport simulation framework.
]])

whatis("Name: SHIELD-HIT12A")
whatis("Category: Physics Simulation")

local root = "/opt/spack/modules/shieldhit"
prepend_path("PATH", pathJoin(root, "bin"))
EOF

    # Configure Elasticsearch for job completion if ELASTICSEARCH_HOST is set
    if [ -n "${ELASTICSEARCH_HOST}" ]; then
        echo "---> Configuring Elasticsearch job completion logging..."
        echo "---> Elasticsearch host: ${ELASTICSEARCH_HOST}"

        # Wait for Elasticsearch to be available
        until curl -s "${ELASTICSEARCH_HOST}/_cluster/health" >/dev/null 2>&1; do
            echo "-- Elasticsearch is not available. Sleeping ..."
            sleep 2
        done
        echo "-- Elasticsearch is now active ..."

        # Update slurm.conf to use Elasticsearch for job completion
        # Format: http://host:port/index/_doc (ES 8.x+ typeless mode)
        sed -i "s|^JobCompType=.*|JobCompType=jobcomp/elasticsearch|" /etc/slurm/slurm.conf
        sed -i "s|^JobCompLoc=.*|JobCompLoc=${ELASTICSEARCH_HOST}/slurm/_doc|" /etc/slurm/slurm.conf

        echo "---> Job completion configured for Elasticsearch"
    fi

    echo "---> Starting the Slurm Controller Daemon (slurmctld) ..."
    exec gosu slurm /usr/sbin/slurmctld -i -Dvvv
fi

if [ "$1" = "slurmrestd" ]
then
    echo "---> Waiting for slurmctld to become active before starting slurmrestd ..."

    until 2>/dev/null >/dev/tcp/slurmctld/6817
    do
        echo "-- slurmctld is not available.  Sleeping ..."
        sleep 2
    done
    echo "-- slurmctld is now active ..."

    echo "---> Starting the Slurm REST API Daemon (slurmrestd) ..."
    # Run slurmrestd on both Unix socket and network port
    # Unix socket provides passwordless local access
    # Note: slurmrestd should NOT be run as SlurmUser or root (security requirement)
    mkdir -p /var/run/slurmrestd
    chown slurmrest:slurmrest /var/run/slurmrestd

    # Export the SLURM_JWT=daemon environment variable before starting the slurmrestd daemon
    # to activate AuthAltTypes=auth/jwt as the primary authentication mechanism
    export SLURM_JWT=daemon; exec gosu slurmrest /usr/sbin/slurmrestd -vvv unix:/var/run/slurmrestd/slurmrestd.socket 0.0.0.0:6820
fi

if [ "$1" = "slurmd-cpu" ]
then
    echo "---> Waiting for slurmctld to become active before starting dynamic slurmd..."

    until 2>/dev/null >/dev/tcp/slurmctld/6817
    do
        echo "-- slurmctld is not available.  Sleeping ..."
        sleep 2
    done
    echo "-- slurmctld is now active ..."

    # Derive a sequential node name from the Docker Compose replica number.
    # e.g., slurm-cpu-worker-1 -> c1, slurm-cpu-worker-2 -> c2
    # Falls back to container ID if replica detection fails.
    REPLICA=$(detect_replica_number "cpu-worker")
    NODE_NAME="c${REPLICA}"
    hostname "${NODE_NAME}"

    echo "---> Dynamic CPU worker registering as: ${NODE_NAME}"
    echo "---> Starting slurmd in dynamic registration mode (-Z)..."

    # -Z: dynamic node self-registration with slurmctld
    # Feature=cpu: tag for cpu partition NodeSet matching
    exec /usr/sbin/slurmd -Z -Dvvv \
        --conf "Feature=cpu"
fi
