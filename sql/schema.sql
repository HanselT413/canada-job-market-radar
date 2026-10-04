-- Canada Job Market Radar: SQLite schema
-- Works in SQLite out of the box; portable to PostgreSQL with minor type changes.

CREATE TABLE IF NOT EXISTS jobs (
    job_id              TEXT PRIMARY KEY,
    source              TEXT NOT NULL,          -- adzuna | greenhouse | lever | ashby | workday
    title               TEXT NOT NULL,
    company             TEXT,
    location            TEXT,
    province            TEXT,
    description         TEXT,
    salary_min          REAL,
    salary_max          REAL,
    salary_is_predicted INTEGER DEFAULT 0,      -- 1 = Adzuna estimate, not employer-posted
    category            TEXT,
    contract_time       TEXT,
    seniority           TEXT,                   -- intern | new_grad | mid | senior | manager
    role_family         TEXT,                   -- data_analyst | product_analyst | ...
    is_staffing_agency  INTEGER DEFAULT 0,      -- 1 = posted by a recruitment agency
    full_description    INTEGER DEFAULT 0,      -- 1 = full JD (company board), 0 = snippet (Adzuna)
    posted_at           TEXT,
    url                 TEXT,
    search_query        TEXT,
    dedupe_key          TEXT,
    first_seen_at       TEXT NOT NULL,
    last_seen_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_skills (
    job_id      TEXT NOT NULL REFERENCES jobs(job_id),
    skill_group TEXT NOT NULL,
    skill       TEXT NOT NULL,
    PRIMARY KEY (job_id, skill)
);

CREATE INDEX IF NOT EXISTS idx_jobs_role ON jobs(role_family);
CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company);
CREATE INDEX IF NOT EXISTS idx_skills_skill ON job_skills(skill);
