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


class CertAuthHandler(BaseHTTPRequestHandler):
    """HTTP request handler for signing user SSH keys using the CA key."""

    def do_GET(self):
        """Handle GET requests to issue signed SSH certificates."""
        # 1. Extract username from Keycloak Authorization header if available
        auth_header = self.headers.get("Authorization", "")
        username = "devuser"  # Fallback default

        if auth_header.startswith("Bearer "):
            token = auth_header.replace("Bearer ", "")
            try:
                # Unverified decode just to inspect claims
                decoded = jwt.decode(token, options={"verify_signature": False})
                username = decoded.get("preferred_username") or decoded.get("username") or "devuser"
            except Exception as e:
                print(f"Warning: Failed to parse Bearer token in Mock CA: {e}")

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
