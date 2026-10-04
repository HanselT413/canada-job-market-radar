"""Build notebooks/market_analysis.ipynb (pandas-only analysis of the radar database)."""
from pathlib import Path

import nbformat as nbf

nb = nbf.v4.new_notebook()
md, code = nbf.v4.new_markdown_cell, nbf.v4.new_code_cell

nb.cells = [
    md("""# Canada Job Market Radar — Analysis in pandas

This notebook reads the database the pipeline builds (`data/radar.db`) and answers the project's questions with plain pandas:

1. Which skills does each type of role ask for?
2. How do skill requirements differ between role types?
3. Who is hiring, and how much of the market goes through recruitment agencies?
4. What seniority levels are open?

**Run first** (in Terminal, from the project folder):
```
export PYTHONPATH=src
python3 -m radar.pipeline fetch      # or: fetch --sample   for the synthetic demo data
```"""),
    md("## 1. Load the data\n\nTwo tables: `jobs` (one row per posting) and `job_skills` (one row per posting–skill pair)."),
    code("""import sqlite3
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

# Works whether the notebook is opened from the project folder or from notebooks/
DB = Path("data/radar.db") if Path("data/radar.db").exists() else Path("../data/radar.db")
conn = sqlite3.connect(DB)

jobs = pd.read_sql("SELECT * FROM jobs", conn)
skills = pd.read_sql("SELECT * FROM job_skills", conn)

print(f"{len(jobs):,} postings, {len(skills):,} posting-skill pairs")
jobs[["title", "company", "location", "source", "role_family", "seniority"]].head()"""),
    md("## 2. How many postings per role type?"),
    code("""role_counts = jobs["role_family"].value_counts()
role_counts"""),
    code("""role_counts.sort_values().plot(kind="barh", figsize=(7, 4), title="Postings by role type")
plt.xlabel("Postings")
plt.tight_layout()
plt.show()"""),
    md("""## 3. Which skills does each role type ask for?

Join skills to jobs, count postings per (role, skill), then divide by the number of postings in that role.

> Adzuna gives only a short snippet of each job description, so skills listed later in a JD are missed.
> Percentages are lower bounds; the **ranking** is more reliable than the exact share."""),
    code("""merged = skills.merge(jobs[["job_id", "role_family"]], on="job_id")

skill_by_role = (
    merged.groupby(["role_family", "skill"])["job_id"].nunique()
    .rename("postings")
    .reset_index()
)
skill_by_role["pct_of_role"] = (
    100 * skill_by_role["postings"] / skill_by_role["role_family"].map(role_counts)
).round(1)

def top_skills(role, n=10):
    return (skill_by_role[skill_by_role["role_family"] == role]
            .sort_values("postings", ascending=False)
            .head(n)[["skill", "postings", "pct_of_role"]])

top_skills("data_analyst")"""),
    md("Change the role name to look at any role type: `product_manager`, `aml_compliance`, `insights_analyst`, `sales_analyst`, `business_analyst`, `risk_analyst`, ..."),
    code("""for role in ["insights_analyst", "sales_analyst", "product_manager", "aml_compliance"]:
    if role in role_counts:
        print(f"\\n=== {role} ({role_counts[role]} postings) ===")
        print(top_skills(role, 8).to_string(index=False))"""),
    md("""## 4. Compare roles side by side

A pivot table (rows = skill, columns = role) shows how requirements differ, e.g. what insights roles ask for that sales roles don't."""),
    code("""compare_roles = [r for r in ["data_analyst", "insights_analyst", "sales_analyst",
                             "product_manager", "aml_compliance"] if r in role_counts]

pivot = (skill_by_role[skill_by_role["role_family"].isin(compare_roles)]
         .pivot_table(index="skill", columns="role_family", values="pct_of_role", fill_value=0))

# keep skills that matter to at least one role
pivot = pivot[pivot.max(axis=1) >= 5].sort_values(compare_roles[0], ascending=False)
pivot"""),
    code("""ax = pivot.plot(kind="barh", figsize=(8, max(4, len(pivot) * 0.35)), width=0.8,
                title="Share of postings mentioning each skill, by role")
ax.invert_yaxis()
plt.xlabel("% of postings in role")
plt.tight_layout()
plt.show()"""),
    md("## 5. Full job descriptions only\n\nCompany job boards (Greenhouse, Lever, Ashby) give the whole JD, so skill shares here are more accurate. Smaller sample, mostly tech and fintech."),
    code("""full = jobs[jobs["full_description"] == 1]
full_skills = skills[skills["job_id"].isin(full["job_id"])]

(full_skills["skill"].value_counts()
 .div(len(full)).mul(100).round(1)
 .rename("pct_of_full_jd_postings")
 .head(15))"""),
    md("## 6. Who is hiring?\n\nRecruitment agencies are flagged so the employer ranking only counts direct employers."),
    code("""agency_share = (jobs["is_staffing_agency"]
                .map({1: "Agency", 0: "Direct employer"})
                .value_counts(normalize=True).mul(100).round(1))
print("Share of postings (%):")
print(agency_share.to_string())

direct = jobs[(jobs["is_staffing_agency"] == 0) & (jobs["company"] != "")]
direct["company"].value_counts().head(15)"""),
    md("## 7. Seniority mix\n\nHow many openings are entry level (`new_grad`) vs. mid or senior, per role type."),
    code("""seniority = pd.crosstab(jobs["role_family"], jobs["seniority"])
seniority["new_grad_share_%"] = (100 * seniority.get("new_grad", 0) / seniority.sum(axis=1)).round(1)
seniority.sort_values("new_grad_share_%", ascending=False)"""),
    md("""## 8. Notes for interpretation

- **Snippets undercount skills** (Adzuna); use rankings and the full-JD section for shares.
- **Full-JD postings skew to tech and fintech**; large banks mostly use applicant systems with no public API.
- **Small groups are noisy**: treat any role type with fewer than ~30 postings as an early signal, not a finding.
- The trend early-warning and salary-premium models are in `src/radar/trends.py` and `src/radar/premium.py`; their results are exported to `data/exports/skill_trends.csv` and `skill_premiums.csv`."""),
    code("""conn.close()"""),
]

nb.metadata["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
out = Path(__file__).resolve().parents[1] / "notebooks" / "market_analysis.ipynb"
out.parent.mkdir(exist_ok=True)
nbf.write(nb, out)
print(f"wrote {out}")
