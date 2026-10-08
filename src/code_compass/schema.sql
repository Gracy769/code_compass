CREATE TABLE IF NOT EXISTS public.analysis_cache (
    repo_hash    varchar      PRIMARY KEY,
    repo_name    varchar      NOT NULL DEFAULT '',
    github_slug  varchar,
    analysis_json jsonb       NOT NULL,
    dash_path    varchar,
    summary_path varchar,
    created_at   timestamptz  NOT NULL DEFAULT now(),
    expires_at   timestamptz  NOT NULL
);

-- Analysis JSON can include private source details. Only the server may access it.
ALTER TABLE public.analysis_cache ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.analysis_cache FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.analysis_cache TO service_role;
