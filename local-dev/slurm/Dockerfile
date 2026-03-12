FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# Install SLURM, munge, SSH server, Python, curl for downloads
RUN apt-get update && apt-get install -y --no-install-recommends \
    slurmd \
    slurmctld \
    slurm-client \
    munge \
    openssh-server \
    python3 \
    python3-pip \
    python3-requests \
    curl \
    libgfortran5 \
    unzip \
    gosu \
    && rm -rf /var/lib/apt/lists/*

# Install pymchelper — provides the real `convertmc` CLI used by the COLLECT_SHIELDHIT_BASH template.
# Version must match pyproject.toml so the JSON output format is compatible with the backend.
RUN pip3 install --no-cache-dir pymchelper==2.8.5

# Download SHIELD-HIT12A demo binary from shieldhit.org.
# The demo version handles all standard input formats produced by yaptide.
# Using a custom User-Agent because shieldhit.org blocks default curl/python UA strings.
ARG SHIELDHIT_DEMO_URL=https://shieldhit.org/download/DEMO/shield_hit12a_x86_64_demo_gfortran_v1.1.0.tar.gz
RUN set -eux; \
    curl -fSL \
    --user-agent "Mozilla/5.0 (Windows NT x.y; rv:10.0) Gecko/20100101 Firefox/10.0" \
    "${SHIELDHIT_DEMO_URL}" \
    -o /tmp/shieldhit_demo.tar.gz; \
    tar -xzf /tmp/shieldhit_demo.tar.gz -C /tmp; \
    find /tmp -name 'shieldhit' -path '*/bin/*' -exec mv {} /usr/local/bin/shieldhit \;; \
    chmod +x /usr/local/bin/shieldhit; \
    rm -rf /tmp/shieldhit_demo.tar.gz /tmp/shield_hit12a*

# Ensure slurm system user/group exist (packages usually create them)
RUN set +e; \
    groupadd -r slurm --gid=997 2>/dev/null; \
    useradd -r -g slurm -u=997 --no-create-home --shell=/sbin/nologin slurm 2>/dev/null

# Create the Linux user that Keycloak's testuser maps to.
# The cert principal (from cert-issuer) and this username must match.
RUN useradd -m -s /bin/bash testuser

# Create scratch directory (batch_methods.py: echo $SCRATCH → /scratch)
RUN mkdir -p /scratch && chmod 777 /scratch

# Required SLURM directories
RUN mkdir -p \
    /var/spool/slurmd \
    /var/spool/slurmctld \
    /var/log/slurm \
    /run/slurm \
    /run/munge \
    /etc/slurm

COPY slurm.conf /etc/slurm/slurm.conf

RUN chown -R slurm:slurm \
    /var/spool/slurmctld \
    /var/log/slurm \
    /run/slurm \
    && chown slurm:slurm /etc/slurm/slurm.conf

# Munge setup — generate a random key at build time.
# Both slurmctld and slurmd share the same container so one key is fine.
RUN dd if=/dev/urandom bs=1 count=1024 > /etc/munge/munge.key 2>/dev/null && \
    chown munge:munge /etc/munge/munge.key && \
    chmod 400 /etc/munge/munge.key

# Make /bin/sh point to bash so that "sh script.sh" honours bash syntax
# (batch_methods.py calls: con.run(f'sh {submit_file}') which ignores the
# #!/bin/bash shebang and would otherwise use dash, breaking brace expansion)
SHELL ["/bin/bash", "-c"]

# SSH setup
RUN mkdir -p /run/sshd /etc/ssh/sshd_config.d && \
    ssh-keygen -A

# Drop in our SSH config: cert-based auth + SCRATCH env export
COPY sshd_config /etc/ssh/sshd_config.d/yaptide.conf

# Helper stubs for tools not available locally:
# - module : no-op — SLURM templates call "module load shieldhit"; we skip Lmod entirely
# - sacct  : thin wrapper around squeue/scontrol — SLURM accounting daemon is not enabled
# shieldhit and convertmc are the real binaries installed above; no stubs needed.
COPY module     /usr/local/bin/module
COPY sacct      /usr/local/bin/sacct
RUN chmod +x \
    /usr/local/bin/module \
    /usr/local/bin/sacct

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 22
ENTRYPOINT ["/entrypoint.sh"]
