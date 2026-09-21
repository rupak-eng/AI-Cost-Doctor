#!/bin/sh
# Entrypoint for the `api` / `worker` services: validate config, run
# migrations, then start the server.
#
# The config check runs FIRST so a missing/invalid FERNET_KEY (or other
# misconfiguration) fails fast with a clear FATAL message instead of a
# cryptic traceback — and before alembic touches the database.
set -e
cd /code
python - <<'PYEOF'
from app.core.config import ConfigurationError, validate_startup_config
try:
    validate_startup_config()
except ConfigurationError as exc:
    print(f"FATAL: invalid configuration — {exc}")
    raise SystemExit(1)
PYEOF
alembic upgrade head
exec "$@"
