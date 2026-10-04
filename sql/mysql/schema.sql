-- Canada Job Market Radar: MySQL schema
-- Run in MySQL Workbench, then load data/exports/tables/*.csv (see sql/mysql/README.md)

CREATE DATABASE IF NOT EXISTS job_radar;
USE job_radar;

DROP TABLE IF EXISTS posting_rules;
DROP TABLE IF EXISTS job_skills;
DROP TABLE IF EXISTS jobs;

CREATE TABLE jobs (
    job_id              VARCHAR(100) PRIMARY KEY,
    source              VARCHAR(20)  NOT NULL,
    title               VARCHAR(300) NOT NULL,
    company             VARCHAR(200),
    location            VARCHAR(200),
    province            VARCHAR(100),
    description         TEXT,
    salary_min          DOUBLE NULL,
    salary_max          DOUBLE NULL,
    salary_is_predicted TINYINT DEFAULT 0,
    category            VARCHAR(100),
    contract_time       VARCHAR(50),
    seniority           VARCHAR(20),
    role_family         VARCHAR(50),
    is_staffing_agency  TINYINT DEFAULT 0,
    full_description    TINYINT DEFAULT 0,
    target_tier         TINYINT DEFAULT 0,
    industry            VARCHAR(60) DEFAULT 'Unclassified',
    posted_at           DATETIME NULL,
    url                 VARCHAR(1000),
    search_query        VARCHAR(200),
    dedupe_key          VARCHAR(500),
    first_seen_at       DATETIME,
    last_seen_at        DATETIME,
    INDEX idx_role (role_family),
    INDEX idx_company (company)
);

CREATE TABLE job_skills (
    job_id      VARCHAR(100) NOT NULL,
    skill_group VARCHAR(50)  NOT NULL,
    skill       VARCHAR(100) NOT NULL,
    PRIMARY KEY (job_id, skill),
    INDEX idx_skill (skill),
    FOREIGN KEY (job_id) REFERENCES jobs(job_id)
);

-- Ontario 2026 job-posting rules: one row per Ontario posting checked
CREATE TABLE posting_rules (
    job_id                       VARCHAR(100) PRIMARY KEY,
    company                      VARCHAR(200),
    industry                     VARCHAR(60),
    role_family                  VARCHAR(50),
    location                     VARCHAR(200),
    target_tier                  TINYINT,
    salary_range_found           TINYINT,      -- 1 = a pay range was detected
    salary_min                   DOUBLE NULL,  -- annualized
    salary_max                   DOUBLE NULL,
    salary_period                VARCHAR(10),  -- annual | hourly (as written in the posting)
    salary_range_width           DOUBLE NULL,
    range_within_cap             TINYINT NULL, -- 1 = width <= $50,000; NULL = no range or pay > $200,000
    ai_disclosure                VARCHAR(10),  -- uses_ai | no_ai | none
    vacancy_statement            VARCHAR(15),  -- existing | not_existing | none
    canadian_experience_required TINYINT,
    INDEX idx_pr_industry (industry),
    FOREIGN KEY (job_id) REFERENCES jobs(job_id)
);
