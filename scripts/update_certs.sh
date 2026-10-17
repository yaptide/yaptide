#!/bin/bash
# Renewal of the TLS certificate: nginx serves the server.crt and server.key docker-compose.yml mounts from the host
# (TLS_CERT_PATH, TLS_KEY_PATH; by default the ones next to docker-compose.yml). Overwrite them in place with the new
# ones (cp or scp, not mv: a mounted file replaced by another file is not seen in the container), then run this.
set -e
docker exec yaptide_nginx nginx -t
docker exec yaptide_nginx nginx -s reload
