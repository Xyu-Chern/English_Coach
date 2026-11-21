#!/usr/bin/env bash
set -euo pipefail
: "${RESPONSES_API_KEY:?Set the model key in Space secrets}"
: "${COACH_PAIR_CODE:?Set the private connection code in Space secrets}"
socket=$(mktemp -d)
pg_ctl -D "$PGDATA" -o "-c listen_addresses='' -k $socket" -l "$socket/postgres.log" -w start
export DATABASE_URL="postgresql://coach_reader@/coach_corpus?host=$socket"
if [[ -n "${SPACE_HOST:-}" ]]; then export COACH_WEB_ORIGIN="https://$SPACE_HOST"; fi
exec python -m frontend.server --host 0.0.0.0 --port "${PORT:-7860}"
