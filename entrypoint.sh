#!/bin/sh
set -e

# Wait for Postgres to accept connections
if [ -n "$DB_HOST" ]; then
  echo "Waiting for database $DB_HOST:$DB_PORT..."
  until python -c "import socket,sys,os; s=socket.socket(); s.settimeout(2); \
sys.exit(0) if (s.connect_ex((os.environ['DB_HOST'], int(os.environ.get('DB_PORT','5432'))))==0) else sys.exit(1)" 2>/dev/null; do
    sleep 1
  done
  echo "Database is up."
fi

# Skip migrate/collectstatic for the parser worker — only the web container needs them.
if [ "$RUN_MIGRATIONS" = "true" ]; then
  echo "Running migrations..."
  python manage.py migrate --noinput
  echo "Collecting static files..."
  python manage.py collectstatic --noinput
fi

exec "$@"
