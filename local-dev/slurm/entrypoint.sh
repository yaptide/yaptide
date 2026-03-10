#!/bin/bash
# Container entrypoint: start munge, sshd, slurmd, then slurmctld (foreground).
set -e

echo "[entrypoint] Starting munge..."
mkdir -p /run/munge
chown munge:munge /run/munge
/usr/sbin/munged --force

echo "[entrypoint] Starting sshd..."
/usr/sbin/sshd

echo "[entrypoint] Starting slurmd..."
/usr/sbin/slurmd -D -N slurm &
SLURMD_PID=$!

# Give slurmd a moment to initialise before slurmctld tries to contact it.
sleep 2

echo "[entrypoint] Starting slurmctld (foreground)..."
/usr/sbin/slurmctld -D &
SLURMCTLD_PID=$!

# Wait for slurmctld to be ready then ensure the node is not stuck in DRAIN
# (can happen after unclean job termination, e.g. in a container environment)
(
  sleep 5
  while ! scontrol ping 2>/dev/null | grep -q 'UP'; do sleep 2; done
  scontrol update node=slurm state=resume 2>/dev/null || true
  echo "[entrypoint] Node resumed."
) &

wait $SLURMCTLD_PID
