-- Load the CSV dumps into MySQL.
-- 1. In the project folder run:  python3 -m radar.pipeline export-tables
-- 2. Replace /PATH/TO with the absolute path of your project folder
--    (in Terminal, run `pwd` inside the project folder to see it).
-- 3. Run sql/mysql/schema.sql first, then this file.

USE job_radar;

LOAD DATA LOCAL INFILE '/PATH/TO/canada-job-market-radar/data/exports/tables/jobs.csv'
INTO TABLE jobs
FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
LINES TERMINATED BY '\r\n'
IGNORE 1 LINES
(job_id, source, title, company, location, province, description, salary_min, salary_max, salary_is_predicted, category, contract_time, seniority, role_family, is_staffing_agency, full_description, target_tier, industry, posted_at, url, search_query, dedupe_key, first_seen_at, last_seen_at);

LOAD DATA LOCAL INFILE '/PATH/TO/canada-job-market-radar/data/exports/tables/job_skills.csv'
INTO TABLE job_skills
FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
LINES TERMINATED BY '\r\n'
IGNORE 1 LINES
(job_id, skill_group, skill);

-- Sanity check
SELECT (SELECT COUNT(*) FROM jobs) AS jobs, (SELECT COUNT(*) FROM job_skills) AS job_skills;
