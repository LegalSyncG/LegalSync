#!/bin/sh
set -e

echo "Starting LegalSync container..."

: "${FLASK_ENV:=production}"
: "${USE_MIGRATIONS:=true}"

if [ "$FLASK_ENV" = "production" ] && [ "$USE_MIGRATIONS" = "true" ]; then
  echo "Running database migrations..."
  flask db upgrade
else
  echo "Skipping migrations (FLASK_ENV=$FLASK_ENV, USE_MIGRATIONS=$USE_MIGRATIONS)"
fi

echo "Starting Gunicorn..."
exec "$@"
