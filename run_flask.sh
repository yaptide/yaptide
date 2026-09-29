#!/bin/sh
set -e
# gunicorn runs several worker processes, they have to sign and verify tokens with the same secrets -
# drawn once here unless the deployment provides its own (then tokens also survive a restart)
YAPTIDE_TOKEN_SECRET="${YAPTIDE_TOKEN_SECRET:-$(python -c 'import secrets; print(secrets.token_hex(256))')}"
YAPTIDE_REFRESH_TOKEN_SECRET="${YAPTIDE_REFRESH_TOKEN_SECRET:-$(python -c 'import secrets; print(secrets.token_hex(256))')}"
export YAPTIDE_TOKEN_SECRET YAPTIDE_REFRESH_TOKEN_SECRET

# create the tables once, before the workers start and race each other doing it
python -c "from yaptide.application import create_app; create_app()"

# threaded workers: a request waiting on the cluster over SSH or a large results upload must not block a whole
# worker, and must not be killed by the 30 s default timeout (nginx in front waits 60 s)
exec gunicorn --worker-class gthread --workers "${GUNICORN_WORKERS:-4}" --threads "${GUNICORN_THREADS:-8}" \
    --timeout "${GUNICORN_TIMEOUT:-300}" --access-logfile - --bind 0.0.0.0:6000 "yaptide.application:create_app()"
