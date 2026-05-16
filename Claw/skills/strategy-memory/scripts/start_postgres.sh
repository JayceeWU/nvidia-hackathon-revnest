#!/usr/bin/env bash
set -euo pipefail

PG_BIN="${STRATEGY_MEMORY_PG_BIN:-/usr/lib/postgresql/17/bin}"
PGDATA="${STRATEGY_MEMORY_PGDATA:-/sandbox/.openclaw/workspace/.postgres/strategy-memory}"
PGHOST="${STRATEGY_MEMORY_PGHOST:-127.0.0.1}"
PGPORT="${STRATEGY_MEMORY_PGPORT:-55434}"
PGDATABASE="${STRATEGY_MEMORY_PGDATABASE:-dev}"
PGUSER="${STRATEGY_MEMORY_PGUSER:-postgres}"
PGPASSWORD_VALUE="${STRATEGY_MEMORY_PGPASSWORD:-postgres}"
LOG_FILE="${PGDATA}/postgres.log"

if "$PG_BIN/pg_isready" -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" >/dev/null 2>&1; then
  exit 0
fi

mkdir -p "$PGDATA"

if [ ! -f "$PGDATA/PG_VERSION" ]; then
  pwfile="$(mktemp)"
  printf '%s\n' "$PGPASSWORD_VALUE" >"$pwfile"
  "$PG_BIN/initdb" \
    -D "$PGDATA" \
    --username="$PGUSER" \
    --pwfile="$pwfile" \
    --auth-local=trust \
    --auth-host=md5 \
    --encoding=UTF8 \
    --no-locale
  rm -f "$pwfile"
fi

if ! "$PG_BIN/pg_ctl" -D "$PGDATA" status >/dev/null 2>&1; then
  "$PG_BIN/pg_ctl" \
    -D "$PGDATA" \
    -l "$LOG_FILE" \
    -o "-c listen_addresses=${PGHOST} -c port=${PGPORT} -c unix_socket_directories=${PGDATA}" \
    start
fi

export PGPASSWORD="$PGPASSWORD_VALUE"
if ! "$PG_BIN/psql" -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = '${PGDATABASE}'" | grep -qx "1"; then
  "$PG_BIN/createdb" -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" "$PGDATABASE"
fi
