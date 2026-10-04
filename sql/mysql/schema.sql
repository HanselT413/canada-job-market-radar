-- Canada Job Market Radar: MySQL schema
-- Run in MySQL Workbench, then load data/exports/tables/*.csv (see sql/mysql/README.md)

CREATE DATABASE IF NOT EXISTS job_radar;
USE job_radar;

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
