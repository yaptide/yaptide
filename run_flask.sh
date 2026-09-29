#!/bin/sh
set -e
# gunicorn runs several worker processes, they have to sign and verify tokens with the same secrets -
# drawn once here unless the deployment provides its own (then tokens also survive a restart)
if [ -z "$YAPTIDE_TOKEN_SECRET" ] || [ -z "$YAPTIDE_REFRESH_TOKEN_SECRET" ]; then
    echo "WARNING: YAPTIDE_TOKEN_SECRET / YAPTIDE_REFRESH_TOKEN_SECRET not set - a restart invalidates all tokens" >&2
    echo "WARNING: and the update keys of running HPC jobs" >&2
fi
YAPTIDE_TOKEN_SECRET="${YAPTIDE_TOKEN_SECRET:-$(python -c 'import secrets; print(secrets.token_hex(256))')}"
YAPTIDE_REFRESH_TOKEN_SECRET="${YAPTIDE_REFRESH_TOKEN_SECRET:-$(python -c 'import secrets; print(secrets.token_hex(256))')}"
export YAPTIDE_TOKEN_SECRET YAPTIDE_REFRESH_TOKEN_SECRET

# create the tables once, before the workers start and race each other doing it
python -c "from yaptide.application import create_app; create_app()"

# sync workers - for the short CPU-bound status requests they kept p99 at 0.3-0.4 s where gthread 4x8 reached
# 3.5-11 s (replayed 5000-task Ares traffic, 2 CPUs); the timeout lets large /results uploads finish instead of
# killing them mid-write after the default 30 s
exec gunicorn --workers "${GUNICORN_WORKERS:-4}" --timeout "${GUNICORN_TIMEOUT:-300}" --access-logfile - \
    --bind 0.0.0.0:6000 "yaptide.application:create_app()"
