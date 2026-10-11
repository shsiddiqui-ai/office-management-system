
#!/usr/bin/env bash
set -e

echo "Starting Office Management System..."

if [ ! -f "database/office_demo.db" ]; then
    echo "Demo database not found. Creating fictional demo database..."
    python database/seed_demo.py --create
else
    echo "Existing demo database found."
fi

echo "Starting Flask application..."

exec gunicorn --bind "0.0.0.0:${PORT:-10000}" app:app
