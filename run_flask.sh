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

# migrate or create the tables once, before the workers start and race each other doing it
python -c "
from yaptide.application import create_app
from yaptide.persistence.models import prepare_database
with create_app().app_context():
    prepare_database()
"

# workers, timeout and logging come from gunicorn.conf.py (GUNICORN_WORKERS and GUNICORN_TIMEOUT override them)
exec gunicorn "yaptide.application:create_app()"
