# This directory holds the SSH Certificate Authority key pair.
# ca.pub  — public key, safe to commit, used by SLURM's TrustedUserCAKeys
# ca_key  — PRIVATE key, gitignored, used by cert-issuer to sign user certs
#
# Generate with:
#   bash local-dev/generate_ssh_ca.sh
