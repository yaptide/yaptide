#!/bin/bash
# Renewal of the TLS certificate: nginx serves the server.crt and server.key docker-compose.yml mounts from the host
# (TLS_CERT_PATH, TLS_KEY_PATH; by default the ones next to docker-compose.yml). Overwrite them in place with the new
# ones (cp or scp, not mv: a mounted file replaced by another file is not seen in the container), then run this
# next to docker-compose.yml.
set -e
cert=${TLS_CERT_PATH:-server.crt}
# nginx would reload its old certificate: the file was replaced (mv), or it was missing when the container started
# (then nginx uses the self-signed one)
if ! docker exec yaptide_nginx cat /etc/nginx/conf.d/server.crt | cmp -s - "$cert"; then
    echo "nginx does not see $cert: copy it over the old one in place, or recreate the container" \
        "(docker compose up -d --no-deps nginx)" >&2
    exit 1
fi
docker exec yaptide_nginx nginx -t
docker exec yaptide_nginx nginx -s reload
