#!/usr/bin/env bash
set -euo pipefail
socket=$(mktemp -d)
export PGHOST="$socket" PGPORT=5432
initdb -D "$PGDATA" --encoding=UTF8 --locale=C --auth-local=trust --auth-host=reject >/dev/null
pg_ctl -D "$PGDATA" -o "-c listen_addresses='' -k $socket" -l "$socket/postgres.log" -w start
trap 'pg_ctl -D "$PGDATA" -m fast -w stop' EXIT
createdb coach_corpus
psql -X -v ON_ERROR_STOP=1 -d coach_corpus -c 'CREATE EXTENSION vector'
psql -X -v ON_ERROR_STOP=1 -d coach_corpus -f review_scope.sql
pg_restore --exit-on-error --no-owner --no-privileges --single-transaction -d coach_corpus corpus.dump
psql -X -v ON_ERROR_STOP=1 -d coach_corpus <<'SQL'
CREATE ROLE coach_reader LOGIN;
GRANT USAGE ON SCHEMA public TO coach_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO coach_reader;
ALTER ROLE coach_reader SET default_transaction_read_only=on;
SQL
