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
    md("""## 7. Which skills are rising? (last 14 days vs the 14 days before)

For job seekers this is the key question. The idea in plain pandas: split postings by publish date into two windows and compare each skill's share.

> **Caveat:** on the first runs, the earlier window only contains postings that are *still open*, so it under-represents roles that filled quickly. Running the radar daily removes this bias over time."""),
    code("""WINDOW_DAYS = 14

dated = jobs.assign(posted=pd.to_datetime(jobs["posted_at"], utc=True, errors="coerce", format="mixed"))
dated = dated.dropna(subset=["posted"])
end = dated["posted"].max()
dated["window"] = None
dated.loc[dated["posted"] > end - pd.Timedelta(days=WINDOW_DAYS), "window"] = "recent"
dated.loc[(dated["posted"] <= end - pd.Timedelta(days=WINDOW_DAYS))
          & (dated["posted"] > end - pd.Timedelta(days=2 * WINDOW_DAYS)), "window"] = "prior"
dated = dated.dropna(subset=["window"])

n_window = dated["window"].value_counts()
share = (skills.merge(dated[["job_id", "window"]], on="job_id")
         .groupby(["skill", "window"])["job_id"].nunique().unstack(fill_value=0)
         .div(n_window, axis=1).mul(100).round(1))
share["change_pp"] = share.get("recent", 0) - share.get("prior", 0)
print(f"Postings: {n_window.to_dict()}")
share.sort_values("change_pp", ascending=False).head(15)"""),
    md("The pipeline adds a statistical test to the same comparison (two-proportion z-test with a false-discovery-rate correction), so only changes that are unlikely to be noise are labelled **RISING** / **FALLING**; **WATCH** means promising but not yet conclusive."),
    code("""EXPORTS = DB.parent / "exports"
trends = pd.read_csv(EXPORTS / "skill_trends.csv")
trends[trends["signal"] != "stable"] if "signal" in trends else trends"""),
    md("### AI skills by industry\n\nHow often postings in each industry mention AI-related skills."),
    code("""ind = skills.merge(jobs[["job_id", "industry"]], on="job_id")
ai = ind[ind["skill_group"] == "ai"]
industry_n = jobs["industry"].value_counts()
ai_share = (ai.groupby(["industry", "skill"])["job_id"].nunique().unstack(fill_value=0)
            .div(industry_n, axis=0).mul(100).round(1)
            .dropna(how="all"))
ai_share[industry_n.reindex(ai_share.index) >= 20] if not ai_share.empty else ai_share"""),
    code("""by_industry_file = EXPORTS / "skill_trends_by_industry.csv"
if by_industry_file.exists() and by_industry_file.stat().st_size > 1:
    by_ind = pd.read_csv(by_industry_file)
    display(by_ind[by_ind["signal"] != "stable"].sort_values(["industry", "change_pp"], ascending=[True, False]))
else:
    print("Not enough postings per industry yet.")"""),
    md("""## 8. Ontario job-posting rules (in force since January 1, 2026)

Ontario employers with 25+ employees must now state a pay range (no wider than $50,000), say whether the posting is for an existing vacancy, disclose AI use in screening applicants, and not require "Canadian experience".

The radar checks Ontario postings with a full job description published since 2026-01-01. Detection is automated text matching, so read the figures as **"detected in the posting"**, not as a legal finding of compliance."""),
    code("""rules_file = EXPORTS / "ontario_rules_summary.csv"
if rules_file.exists():
    display(pd.read_csv(rules_file))
    by_ind = pd.read_csv(EXPORTS / "ontario_rules_by_industry.csv")
    display(by_ind)
    by_ind.set_index("industry")[["pct_salary_range", "pct_vacancy_statement", "pct_ai_statement"]].plot(
        kind="barh", figsize=(8, max(3, len(by_ind) * 0.45)), title="Share of Ontario postings with each element (%)")
    plt.tight_layout(); plt.show()
else:
    print("No in-scope postings yet: run fetch on live data first.")"""),
    code("""# Look at individual postings, e.g. ranges wider than the $50,000 cap
rules = pd.read_sql("SELECT * FROM posting_rules", conn) if rules_file.exists() else pd.DataFrame()
if not rules.empty:
    display(rules[rules["range_within_cap"] == 0][["company", "role_family", "salary_min", "salary_max", "salary_range_width"]].head(20))"""),
    md("## 9. Target employers\n\nPostings from the companies in `config/target_companies.yaml` (tier 1 = top choices, tier 2 = solid alternatives)."),
    code("""targets = jobs[jobs["target_tier"] > 0]
print(f"{len(targets)} open roles at target employers "
      f"({(targets['target_tier'] == 1).sum()} tier 1, {(targets['target_tier'] == 2).sum()} tier 2)")

summary = (targets.groupby(["target_tier", "company"])
           .agg(open_roles=("job_id", "count"),
                entry_level=("seniority", lambda s: s.isin(["new_grad", "intern"]).sum()),
                role_types=("role_family", lambda s: ", ".join(sorted(set(s)))))
           .sort_values(["target_tier", "open_roles"], ascending=[True, False]))
summary.head(25)"""),
    code("""# Tier 1 roles by role type: where your target employers are hiring
pd.crosstab(targets["company"], targets["role_family"]).loc[
    targets.loc[targets["target_tier"] == 1, "company"].value_counts().index[:15]]"""),
    md("## 10. Seniority mix\n\nHow many openings are entry level (`new_grad`) vs. mid or senior, per role type."),
    code("""seniority = pd.crosstab(jobs["role_family"], jobs["seniority"])
seniority["new_grad_share_%"] = (100 * seniority.get("new_grad", 0) / seniority.sum(axis=1)).round(1)
seniority.sort_values("new_grad_share_%", ascending=False)"""),
    md("""## 11. Notes for interpretation

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
