-- Time anchors: transcript positions with a known audio time (storage/episode_audio.py).
-- Written by `jobs/podcast_audio.py anchors` from inline markers the publisher left in the text, e.g.
-- "[08:24]" or "[01:04:02.14]" (raw Markdown "\[08:24\]"): the audio time where the next paragraph starts.
--   char_offset  document offset in the coordinates of build_id: a position in the concatenation of that
--                build's cue texts with no separator, "".join(cue->>'text' for cue in corpus_builds.cues),
--                i.e. the char_start/char_end/char_total the audio estimate computes
--                (storage/episode_audio.py audio_clips_for_chunks). Quote offsets are chunk-relative; map
--                them with episode_audio.chunk_to_document_offset before interpolating.
--   time_ms      audio time at that offset (ms)
--   source       'inline_marker'        publisher marker; char_offset = first character after it
--                'segment_start'        a marker-only cue labelled Break/Outro/Jingle/...: untranscribed
--                                       audio starts here; char_offset = end of the preceding speech
--                'segment_end_estimate' derived, not written by the publisher: where the speech after that
--                                       segment starts, estimated back from the next anchor at the
--                                       document's speech rate (never before the segment start)
--   build_id     the corpus build whose cue texts define char_offset; a rebuild replaces the rows
-- Additive only and safe to apply to an existing DB; derived data, rebuilt by rerunning the job.
BEGIN;

CREATE TABLE IF NOT EXISTS public.transcript_time_anchors (
    document_id uuid NOT NULL REFERENCES public.podcast_transcripts(document_id) ON DELETE CASCADE,
    char_offset integer NOT NULL CHECK (char_offset >= 0),
    time_ms integer NOT NULL CHECK (time_ms >= 0),
    source text NOT NULL CHECK (source IN ('inline_marker', 'segment_start', 'segment_end_estimate')),
    build_id uuid NOT NULL REFERENCES public.corpus_builds(build_id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (document_id, char_offset)
);

CREATE INDEX IF NOT EXISTS transcript_time_anchors_build_idx
    ON public.transcript_time_anchors (build_id, char_offset);

COMMIT;
