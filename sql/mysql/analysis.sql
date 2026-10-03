-- Canada Job Market Radar: analysis queries (MySQL 8 dialect)
USE job_radar;

-- 1. Skill demand: share of postings mentioning each skill
SELECT
    s.skill_group,
    s.skill,
    COUNT(DISTINCT s.job_id) AS postings,
    ROUND(100.0 * COUNT(DISTINCT s.job_id) / (SELECT COUNT(*) FROM jobs), 1) AS pct_of_postings
FROM job_skills s
GROUP BY s.skill_group, s.skill
ORDER BY postings DESC;

-- 2. Skill demand within each role family
SELECT
    j.role_family,
    s.skill,
    COUNT(*) AS postings,
    ROUND(100.0 * COUNT(*) / t.role_total, 1) AS pct_within_role
FROM job_skills s
JOIN jobs j ON j.job_id = s.job_id
JOIN (SELECT role_family, COUNT(*) AS role_total FROM jobs GROUP BY role_family) t
  ON t.role_family = j.role_family
GROUP BY j.role_family, s.skill, t.role_total
ORDER BY j.role_family, postings DESC;

-- 3. Average posted salary midpoint by skill (employer-posted only)
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

-- 4. Top hiring companies
SELECT
    company,
    COUNT(*) AS open_roles,
    GROUP_CONCAT(DISTINCT role_family ORDER BY role_family SEPARATOR ', ') AS role_families
FROM jobs
WHERE company <> ''
GROUP BY company
ORDER BY open_roles DESC
LIMIT 25;

-- 5. Seniority mix by role family
SELECT role_family, seniority, COUNT(*) AS postings
FROM jobs
GROUP BY role_family, seniority
ORDER BY role_family, postings DESC;

-- 6. New postings per week
SELECT
    DATE_FORMAT(posted_at, '%x-W%v') AS year_week,
    role_family,
    COUNT(*) AS postings
FROM jobs
WHERE posted_at IS NOT NULL
GROUP BY year_week, role_family
ORDER BY year_week;

-- 7. Practice: window function — each skill's rank within its role family
SELECT *
FROM (
    SELECT
        j.role_family,
        s.skill,
        COUNT(*) AS postings,
        RANK() OVER (PARTITION BY j.role_family ORDER BY COUNT(*) DESC) AS skill_rank
    FROM job_skills s
    JOIN jobs j ON j.job_id = s.job_id
    GROUP BY j.role_family, s.skill
) ranked
WHERE skill_rank <= 5
ORDER BY role_family, skill_rank;
