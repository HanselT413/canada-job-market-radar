-- Canada Job Market Radar: analysis queries
-- Each query is separated by a "-- name:" header so the pipeline can export them for Tableau.

-- name: skill_demand
-- Share of postings mentioning each skill, overall
SELECT
    s.skill_group,
    s.skill,
    COUNT(DISTINCT s.job_id)                                         AS postings,
    ROUND(100.0 * COUNT(DISTINCT s.job_id) / (SELECT COUNT(*) FROM jobs), 1) AS pct_of_postings
FROM job_skills s
GROUP BY s.skill_group, s.skill
ORDER BY postings DESC;

-- name: skill_demand_full_jd
-- Same as skill_demand, but only postings with a full job description (company boards).
-- More accurate skill shares; Adzuna snippets undercount skills listed later in a JD.
SELECT
    s.skill_group,
    s.skill,
    COUNT(DISTINCT s.job_id) AS postings,
    ROUND(100.0 * COUNT(DISTINCT s.job_id)
          / (SELECT COUNT(*) FROM jobs WHERE full_description = 1), 1) AS pct_of_postings
FROM job_skills s
JOIN jobs j ON j.job_id = s.job_id
WHERE j.full_description = 1
GROUP BY s.skill_group, s.skill
ORDER BY postings DESC;

-- name: skill_by_role
-- Skill demand within each role family
SELECT
    j.role_family,
    s.skill,
    COUNT(*) AS postings,
    ROUND(100.0 * COUNT(*) / t.role_total, 1) AS pct_within_role
FROM job_skills s
JOIN jobs j ON j.job_id = s.job_id
JOIN (SELECT role_family, COUNT(*) AS role_total FROM jobs GROUP BY role_family) t
  ON t.role_family = j.role_family
GROUP BY j.role_family, s.skill
ORDER BY j.role_family, postings DESC;

-- name: salary_by_skill
-- Average posted salary midpoint for jobs that mention each skill (employer-posted salaries only)
SELECT
    s.skill,
    COUNT(*) AS postings_with_salary,
    ROUND(AVG((j.salary_min + j.salary_max) / 2.0), 0) AS avg_salary_mid
FROM job_skills s
JOIN jobs j ON j.job_id = s.job_id
WHERE j.salary_min IS NOT NULL
  AND j.salary_max IS NOT NULL
  AND j.salary_is_predicted = 0
GROUP BY s.skill
HAVING COUNT(*) >= 3
ORDER BY avg_salary_mid DESC;

-- name: top_hiring_companies
-- Direct employers only (recruitment agencies excluded)
SELECT
    company,
    COUNT(*) AS open_roles,
    GROUP_CONCAT(DISTINCT role_family) AS role_families
FROM jobs
WHERE company <> '' AND is_staffing_agency = 0
GROUP BY company
ORDER BY open_roles DESC
LIMIT 25;

-- name: agency_share
-- How much of the market is posted through recruitment agencies
SELECT
    CASE WHEN is_staffing_agency = 1 THEN 'Agency' ELSE 'Direct employer' END AS poster_type,
    COUNT(*) AS postings,
    ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM jobs), 1) AS pct_of_postings
FROM jobs
GROUP BY poster_type;

-- name: seniority_mix
SELECT
    role_family,
    seniority,
    COUNT(*) AS postings
FROM jobs
GROUP BY role_family, seniority
ORDER BY role_family, postings DESC;

-- name: postings_by_week
SELECT
    strftime('%Y-%W', posted_at) AS year_week,
    role_family,
    COUNT(*) AS postings
FROM jobs
WHERE posted_at <> ''
GROUP BY year_week, role_family
ORDER BY year_week;
