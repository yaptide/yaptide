#!/bin/bash
# Generates the SSH Certificate Authority key pair used by:
#   - cert-issuer (signs user certificates with ca_key)
#   - SLURM container (trusts ca_key.pub via TrustedUserCAKeys)
#
# Run ONCE before starting docker compose:
#   bash local-dev/generate_ssh_ca.sh
#
# ca_key      → NEVER commit (gitignored)
# ca_key.pub  → safe to commit; auto-generated alongside ca_key

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CA_DIR="${SCRIPT_DIR}/ssh-ca"

if [[ -f "${CA_DIR}/ca_key" ]]; then
    echo "CA key already exists at ${CA_DIR}/ca_key."
    echo "Remove it to regenerate."
    exit 1
fi

mkdir -p "${CA_DIR}"

ssh-keygen -t rsa -b 4096 -f "${CA_DIR}/ca_key" -N "" -C "yaptide-local-dev-ca"

echo ""
echo "SSH CA key pair generated:"
echo "  Private: ${CA_DIR}/ca_key      <- NEVER commit this"
echo "  Public:  ${CA_DIR}/ca_key.pub  <- safe to commit"
echo ""
echo "Next: docker compose -f local-dev/docker-compose-local-slurm.yml up --build"
