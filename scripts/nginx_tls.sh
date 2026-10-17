#!/bin/sh
# Run by the nginx image at start (/docker-entrypoint.d): nginx.conf reads conf.d/server.crt and server.key, linked
# here to the pair docker-compose.yml mounts from the host (TLS_CERT_PATH, TLS_KEY_PATH) - linked, so a renewal is
# replacing the host files and `nginx -s reload` (scripts/update_certs.sh). Without them the self-signed pair built
# into the image is used.
mounted=/etc/nginx/certs
# a missing host file is mounted as an empty directory, made by docker
if [ -f $mounted/server.crt ] && [ -s $mounted/server.crt ] && [ -f $mounted/server.key ] \
    && [ -s $mounted/server.key ]; then
    source=$mounted
else
    echo "$0: no TLS certificate and key in $mounted, using the self-signed ones"
    source=/etc/nginx/self-signed
fi
ln -sf $source/server.crt /etc/nginx/conf.d/server.crt
ln -sf $source/server.key /etc/nginx/conf.d/server.key
