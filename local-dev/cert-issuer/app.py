"""
Dummy SSH Certificate Issuer — local development only.

Accepts:  GET /key
          Authorization: Bearer <keycloak_token>

Returns:  {"cert": "<ssh-rsa-cert.pub content>", "private": "<RSA PEM private key>"}

The certificate is signed by the CA whose private key is mounted at CA_KEY_PATH.
The CA public key must be listed in the SLURM container's sshd TrustedUserCAKeys.

In dev mode the Keycloak token is decoded WITHOUT signature verification.
The `preferred_username` claim is used as the certificate principal so that
it matches the Linux user account on the SLURM node.

NEVER expose this service on a public network.
"""

import logging
import subprocess
import tempfile
import uuid
from pathlib import Path

import jwt
from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse

CA_KEY_PATH = "/ca_key"

app = FastAPI()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@app.get("/key")
def get_ssh_cert(authorization: str = Header(default="")) -> JSONResponse:
    """
    Issue a short-lived RSA key + SSH certificate for the requesting user.

    The certificate principal equals the Keycloak `preferred_username` so it
    matches the Linux user created in the SLURM container.
    """
    token = authorization.removeprefix("Bearer ").strip()

    # Dev mode: decode without signature verification
    username = "testuser"
    if token:
        try:
            decoded = jwt.decode(token, options={"verify_signature": False})
            username = decoded.get("preferred_username", "testuser")
        except Exception as exc:
            logger.warning("Could not decode token (%s) - using default username 'testuser'", exc)

    logger.info("Issuing SSH certificate for principal: %s", username)

    with tempfile.TemporaryDirectory() as tmpdir:
        key_path = Path(tmpdir) / f"{uuid.uuid4()}_key"

        ssh_keygen = "/usr/bin/ssh-keygen"
        if not Path(ssh_keygen).is_file():
            raise FileNotFoundError(f"ssh-keygen not found at expected path: {ssh_keygen}")

        # Generate RSA 2048 key in traditional PEM format.
        # Must be RSA — paramiko's RSAKey.from_private_key() requires RSA.
        # -m PEM produces the classic -----BEGIN RSA PRIVATE KEY----- header
        # which both old and new paramiko versions handle reliably.
        subprocess.run(
            [
                ssh_keygen,
                "-t",
                "rsa",
                "-b",
                "2048",
                "-m",
                "PEM",
                "-f",
                str(key_path),
                "-N",
                "",
            ],
            check=True,
            capture_output=True,
        )

        pub_key_path = Path(str(key_path) + ".pub")

        # Sign the public key with the CA.
        # -n <principal> must match the Linux username on the SLURM node.
        subprocess.run(
            [
                ssh_keygen,
                "-s",
                CA_KEY_PATH,
                "-I",
                f"{username}@yaptide-local-dev",
                "-n",
                username,
                "-V",
                "+24h",
                str(pub_key_path),
            ],
            check=True,
            capture_output=True,
        )

        cert_path = Path(str(key_path) + "-cert.pub")

        # pkey.load_certificate(cert) in paramiko expects the raw cert.pub
        # file content: "ssh-rsa-cert-v01@openssh.com AAAA... comment\n"
        private_key = key_path.read_text()
        cert = cert_path.read_text()

    logger.info("Certificate issued successfully for: %s", username)
    return JSONResponse({"cert": cert, "private": private_key})
