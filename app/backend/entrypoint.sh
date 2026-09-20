#!/bin/sh
# Entrypoint for the `api` service: run migrations, then start the server.
set -e
cd /code
alembic upgrade head
exec "$@"
