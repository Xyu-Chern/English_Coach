CREATE TABLE IF NOT EXISTS public.coach_workflow_runs (
    request_id uuid PRIMARY KEY,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    metrics jsonb NOT NULL
);

CREATE OR REPLACE VIEW public.coach_workflow_replays WITH (security_invoker = true) AS
SELECT recorded_at,
       'https://phrase-room-coach.vercel.app/api/search?run_id=' || request_id::text AS replay_url,
       round((metrics->>'elapsed_ms')::numeric / 1000, 2) AS elapsed_seconds,
       (metrics->>'searches')::integer AS searches,
       (metrics->>'verified')::integer AS verified,
       request_id
FROM public.coach_workflow_runs;
