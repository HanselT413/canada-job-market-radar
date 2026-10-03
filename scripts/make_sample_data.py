"""Generate the synthetic sample dataset in data/sample/sample_jobs.json.

All companies are fictional. Two patterns are planted on purpose so the demo
and tests can check that the analysis recovers them:
  * dbt demand rises over the 12 weeks (trend early-warning should flag it)
  * dbt (+10%) and Python (+6%) carry a salary premium after controls
"""
import json
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

random.seed(7)
OUT = Path(__file__).resolve().parents[1] / "data" / "sample" / "sample_jobs.json"

COMPANIES = [f"{a} {b}" for a in ["Northbay", "Maple", "Lakeshore", "Aurora", "Pinecrest"]
             for b in ["Financial", "Retail", "Insurance", "Tech"]]
CITIES = ["Toronto, Ontario"] * 5 + ["Mississauga, Ontario", "Ottawa, Ontario", "Remote, Canada",
                                     "Vancouver, British Columbia"]
TEAMS = ["Marketing", "Finance", "Operations", "Risk", "Customer", "Growth", "Payments", "Lending"]
ROLES = {
    "Data Analyst": ["SQL", "Excel", "Tableau", "stakeholders", "dashboards"],
    "Product Analyst": ["SQL", "A/B testing", "funnel", "retention", "Looker"],
    "Business Analyst": ["Excel", "SQL", "stakeholders", "Power BI", "CRM"],
    "Business Intelligence Analyst": ["Power BI", "SQL", "ETL", "dashboards"],
    "AML Analyst": ["AML", "KYC", "SQL", "Excel", "banking"],
}
LEVELS = [("Junior ", 62000), ("", 80000), ("Senior ", 105000)]
CITY_ADJ = {"Toronto": 1.05, "Mississauga": 1.0, "Ottawa": 0.97, "Remote": 1.0, "Vancouver": 1.04}
START = datetime(2026, 7, 6, tzinfo=timezone.utc)  # Monday, 12 weeks before October
WEEKS = 12

jobs = []
for i in range(1000):
    week = random.randrange(WEEKS)
    role, base_skills = random.choice(list(ROLES.items()))
    level, base_salary = random.choice(LEVELS)
    team = random.choice(TEAMS)
    city = random.choice(CITIES)
    skills = random.sample(base_skills, k=random.randint(3, len(base_skills)))

    p_dbt = 0.03 + 0.42 * week / (WEEKS - 1)     # 3% -> 45% over the period
    has_dbt = random.random() < p_dbt
    has_python = random.random() < 0.45
    if has_dbt:
        skills.append("dbt")
    if has_python:
        skills.append("Python")

    log_salary = (math.log(base_salary) + math.log(CITY_ADJ[city.split(",")[0]])
                  + (0.095 if has_dbt else 0) + (0.058 if has_python else 0)
                  + random.gauss(0, 0.08))
    mid = round(math.exp(log_salary), -3)
    has_salary = random.random() < 0.65

    title = f"{level}{role}, {team}"
    jobs.append({
        "job_id": f"sample_{i:03d}",
        "source": random.choice(["adzuna", "adzuna", "greenhouse", "lever"]),
        "title": title,
        "company": random.choice(COMPANIES),
        "location": city,
        "province": "",
        "description": f"<p>We are hiring a {title}. You will use {', '.join(skills)} "
                       f"to turn data into decisions.</p>",
        "salary_min": mid - 7500 if has_salary else None,
        "salary_max": mid + 7500 if has_salary else None,
        "salary_is_predicted": 0,
        "category": "IT Jobs",
        "contract_time": "full_time",
        "posted_at": (START + timedelta(weeks=week, days=random.randrange(7))).isoformat(),
        "url": f"https://example.com/jobs/{i}",
        "search_query": "sample",
    })

dup = dict(jobs[0], job_id="sample_dup", source="greenhouse")  # cross-source duplicate
jobs.append(dup)
OUT.write_text(json.dumps(jobs, indent=1))
print(f"wrote {len(jobs)} postings to {OUT}")
