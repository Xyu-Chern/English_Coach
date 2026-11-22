-- The live request log and the coach mode switch (frontend/request_log.py).
-- The server runs this file when it starts; every statement is safe to run again.
-- One row per answered or refused POST /api/search, written after the response ends.
-- question is the learner's question only (never the context); result keeps the RunResult's trace,
-- expressions and usage (not its rendered answer) so /admin/requests.json can show the request.

CREATE TABLE IF NOT EXISTS coach_request_log (
    id              bigserial PRIMARY KEY,
    created_at      timestamptz NOT NULL DEFAULT now(),
    mode            text NOT NULL,
    mode_source     text,
    transport       text NOT NULL,
    status          text NOT NULL,
    error_code      text,
    question        text,
    quick_ms        integer,
    first_ms        integer,
    total_ms        integer NOT NULL DEFAULT 0,
    llm_calls       integer NOT NULL DEFAULT 0,
    searches        integer NOT NULL DEFAULT 0,
    input_tokens    integer NOT NULL DEFAULT 0,
    output_tokens   integer NOT NULL DEFAULT 0,
    verified_first  integer,
    added_final     integer NOT NULL DEFAULT 0,
    verified_final  integer,
    continuation    text,
    result          jsonb
);

CREATE INDEX IF NOT EXISTS coach_request_log_created_at ON coach_request_log (created_at DESC);

-- key 'coach_system' = 'baseline' | 'agent' overrides COACH_SYSTEM (cached 10 s per server process).
CREATE TABLE IF NOT EXISTS coach_settings (
    key         text PRIMARY KEY,
    value       text NOT NULL,
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS coach_mode_changes (
    id          bigserial PRIMARY KEY,
    at          timestamptz NOT NULL DEFAULT now(),
    from_mode   text,
    to_mode     text NOT NULL
);
