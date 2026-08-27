"""Mock Certificate Authority HTTP server for signing SSH keys."""

import json
import os
import shutil
import subprocess
import tempfile
import jwt  # Make sure PyJWT is in your Dockerfile or requirements
from http.server import BaseHTTPRequestHandler, HTTPServer

CA_KEY_PATH = os.environ.get("CA_KEY_PATH", "/ca_key/ca_key")
SSH_KEYGEN_BIN = shutil.which("ssh-keygen") or "/usr/bin/ssh-keygen"


def resolve_principal_from_token(token):
    """Return the principal name from a bearer token.

    This mock CA must not trust bearer tokens by default. When a signing secret is
    configured, the token signature is verified before principal selection. The only
    insecure escape hatch is an explicit dev-only override for local testing.
    """
    if not token or not isinstance(token, str):
        raise ValueError("Invalid JWT: missing bearer token")

    if token.count(".") != 2:
        raise ValueError("Invalid JWT: malformed token")

    allow_insecure_tokens = os.environ.get("CA_ALLOW_INSECURE_TOKENS", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    try:
        header = jwt.get_unverified_header(token)
    except jwt.InvalidTokenError as exc:
        raise ValueError("Invalid JWT: malformed token header") from exc

    algorithm = header.get("alg")
    signing_secret = os.environ.get("CA_JWT_SECRET")

    if allow_insecure_tokens:
        try:
            claims = jwt.decode(token, options={"verify_signature": False})
        except jwt.InvalidTokenError as exc:
            raise ValueError("Invalid JWT: token could not be decoded") from exc
        if not isinstance(claims, dict):
            raise ValueError("Invalid JWT: payload is not an object")
        username = claims.get("preferred_username") or claims.get("username")
        if not username:
            raise ValueError("Invalid JWT: missing preferred_username claim")
        return str(username)

    if not signing_secret:
        raise ValueError(
            "JWT signature must be verified before trusting a principal; "
            "set CA_JWT_SECRET or CA_ALLOW_INSECURE_TOKENS=1 only for local dev/test use."
        )

    try:
        claims = jwt.decode(token, key=signing_secret, algorithms=[algorithm] if algorithm else ["HS256"])
    except jwt.InvalidTokenError as exc:
        raise ValueError("Invalid JWT: signature verification failed") from exc
    except Exception as exc:  # pragma: no cover - defensive fallback
        raise ValueError("Invalid JWT: token parse failed") from exc

    if not isinstance(claims, dict):
        raise ValueError("Invalid JWT: payload is not an object")

    username = claims.get("preferred_username") or claims.get("username")
    if not username:
        raise ValueError("Invalid JWT: missing preferred_username claim")
    return str(username)


class CertAuthHandler(BaseHTTPRequestHandler):
    """HTTP request handler for signing user SSH keys using the CA key."""

    def do_GET(self):
        """Handle GET requests to issue signed SSH certificates."""
        # 1. Extract username from Keycloak Authorization header if available
        auth_header = self.headers.get("Authorization", "")

        if auth_header.startswith("Bearer "):
            token = auth_header.replace("Bearer ", "", 1).strip()
            try:
                username = resolve_principal_from_token(token)
            except ValueError as exc:
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(exc)}).encode())
                return
        else:
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error": "Missing bearer token"}')
            return

        with tempfile.TemporaryDirectory() as tmpdir:
            user_key = os.path.join(tmpdir, "id_rsa")

            # 2. Generate SSH keypair
            subprocess.run(
                [SSH_KEYGEN_BIN, "-t", "rsa", "-b", "2048", "-f", user_key, "-N", "", "-q"],
                check=True,
            )

            # 3. Sign public key for the extracted principal ($username)
            try:
                subprocess.run(
                    [
                        SSH_KEYGEN_BIN,
                        "-s",
                        CA_KEY_PATH,
                        "-I",
                        f"{username}_cert",
                        "-n",
                        username,
                        "-V",
                        "+1d",
                        f"{user_key}.pub",
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
            except subprocess.CalledProcessError as e:
                # This will print the actual error message from ssh-keygen
                print(f"SSH-KEYGEN FAILED: {e.stderr}", flush=True)
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b"Internal Server Error: Certificate signing failed")
                return

            # 4. Read keys
            with open(user_key, "r", encoding="utf-8") as f:
                private_key = f.read()
            with open(f"{user_key}-cert.pub", "r", encoding="utf-8") as f:
                cert = f.read()

        # 5. Respond with JSON payload expected by Flask backend
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"cert": cert, "private": private_key}).encode())


if __name__ == "__main__":
    host = os.environ.get("CA_HOST", "0.0.0.0")  # nosec B104
    port = int(os.environ.get("CA_PORT", 5001))
    server = HTTPServer((host, port), CertAuthHandler)
    print(f"Cert Auth Server listening on {host}:{port}...")
    server.serve_forever()
