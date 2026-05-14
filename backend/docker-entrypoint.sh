#!/bin/sh
set -e

if [ "${DB_CONNECTION:-sqlite}" = "pgsql" ]; then
  python - <<'PY'
import os
import socket
import sys
import time

host = os.getenv("DB_HOST", "db")
port = int(os.getenv("DB_PORT", "5432"))
timeout_seconds = int(os.getenv("DB_WAIT_TIMEOUT_SECONDS", "60"))
deadline = time.time() + max(timeout_seconds, 1)

while time.time() < deadline:
    try:
        with socket.create_connection((host, port), timeout=2):
            print(f"PostgreSQL reachable at {host}:{port}")
            break
    except OSError:
        time.sleep(1)
else:
    print(f"Timed out waiting for PostgreSQL at {host}:{port}", file=sys.stderr)
    sys.exit(1)
PY
fi

python migrate.py
exec "$@"
