CREATE TABLE IF NOT EXISTS analysis_cache (
    repo_hash    varchar      PRIMARY KEY,
    repo_name    varchar      NOT NULL DEFAULT '',
    github_slug  varchar,
    analysis_json jsonb       NOT NULL,
    dash_path    varchar,
    summary_path varchar,
    created_at   timestamptz  NOT NULL DEFAULT now(),
    expires_at   timestamptz  NOT NULL
);
