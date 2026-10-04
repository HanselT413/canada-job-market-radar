# Canada Job Market Radar

A data pipeline and analytics project that tracks the Canadian job market for analytics roles, and the foundation for an AI-powered resume-to-job matching product.

**Question it answers:** *What skills does the Toronto market actually ask for in analytics, insights, sales, product management and AML / financial-crime roles, which ones pay more, and who is hiring?*

## What it does (Phase 1)

```
Adzuna API ─┐
Greenhouse ─┤
Lever ──────┼─► normalize ─► filter & dedupe ─► skill extraction ─► SQLite ─► SQL / stats ─► CSV ─► Tableau
Ashby ──────┘
```

| Step | File | What happens |
|---|---|---|
| Collect | `src/radar/sources/` | Pulls postings from the Adzuna Canada API and public Greenhouse / Lever / Ashby company job boards |
| Normalize | `normalize_*` functions | Maps each source to one common schema |
| Clean | `src/radar/clean.py` | Strips HTML, tags seniority, role family and recruitment agencies, removes cross-source duplicates |
| Extract skills | `src/radar/skills.py`, `config/skills.yaml` | Transparent dictionary matching across technical, analytics, product-management and AML-compliance skills |
| Store | `sql/schema.sql` | `jobs` and `job_skills` tables (one-to-many) |
| Analyze | `sql/analysis.sql` | Skill demand (all / full-JD only), skills by role, salary by skill, top direct employers, agency share, seniority mix, weekly trend |
| Export | `pipeline.py export` | One CSV per query, ready for Tableau |

## Role families covered

| Role family | Example titles |
|---|---|
| `data_analyst` / `bi_analyst` / `business_analyst` | Data Analyst, BI Analyst, Business Analyst |
| `product_analyst` | Product Analyst |
| `insights_analyst` | Client / Customer / Business / Marketing Insights Analyst |
| `sales_analyst` | Sales Analyst, Sales / Revenue Operations Analyst, Pricing Analyst |
| `product_manager` | Product Manager, Associate Product Manager, Product Owner, Product Associate |
| `aml_compliance` | AML Analyst, KYC Analyst, Financial Crimes Analyst, Compliance Analyst |
| `risk_analyst` | Credit / Market / Operational Risk Analyst |
| `data_scientist` | Data Scientist, ML roles |

Add search terms in `config/search.yaml`; add role rules in `src/radar/clean.py`. `skill_by_role` compares what each family asks for.

## Two analyses that go beyond counting

### 1. Skill trend early-warning (`src/radar/trends.py`)
Which skills are growing fastest in new postings?

- Compares each skill's share of new postings in the last 4 weeks vs the 4 weeks before
- Two-proportion z-test per skill, then a **Benjamini–Hochberg correction** because testing many skills at once inflates false positives
- `RISING` / `FALLING` = survives the correction · `WATCH` = p < 0.05 only · `stable` otherwise
- The radar re-runs weekly, so its history grows over time — a dataset no one else has

### 2. Skill salary premium (`src/radar/premium.py`)
How much more do postings that ask for a skill pay, **after controlling for seniority, role family and city?**

```
log(salary_mid) = b0 + Σ b_k · has_skill_k + seniority + role_family + city + ε
premium_k = exp(b_k) − 1
```

- OLS with robust (HC3) standard errors, 95% confidence intervals, Benjamini–Hochberg q-values
- Only employer-posted salaries; skills need ≥10 postings with and without them
- **Interpretation:** a controlled association, not a causal effect. Employers asking for a skill may differ in ways the model does not observe (company size, industry, team).

**Validation:** the synthetic sample data plants a rising dbt trend and a +10% (dbt) / +6% (Python) premium. The tests check that both are recovered, and that the trend analysis flags nothing else. Both analyses use Benjamini–Hochberg FDR control; skills that always co-occur with another skill or a control are dropped from the regression automatically.

*An honest caveat the sample exposes:* A/B Testing also passes the premium threshold (+5.5%) although no premium was planted. It appears almost only in product-analyst postings, so the comparison group is small (26 postings) and chance differences look significant. On real data, treat premiums for skills concentrated in a single role with caution.

## Quick start

```bash
pip install -r requirements.txt
export PYTHONPATH=src

# Offline demo with synthetic sample data (no API key needed)
python -m radar.pipeline fetch --sample
python -m radar.pipeline export

# Live data
cp .env.example .env        # add your Adzuna app_id and app_key
python -m radar.pipeline fetch
python -m radar.pipeline export

# Tests
pytest
```

**Prefer pandas?** `notebooks/market_analysis.ipynb` reproduces the main analysis with plain pandas (`groupby`, `merge`, `pivot_table`, `crosstab`) and charts, reading the same database.

**Using MySQL?** `python -m radar.pipeline export-tables` dumps the tables as CSV; `sql/mysql/` has the MySQL schema, a loader and the analysis queries. See [sql/mysql/README.md](sql/mysql/README.md).

Edit `config/search.yaml` to change search terms, city, or target companies, and `config/skills.yaml` to add skills. No code changes needed.

## Design decisions

- **Rules before AI for skill tagging.** Every tag is explainable and free to compute; LLM extraction is layered on in Phase 2.
- **Employer-posted salaries only.** Adzuna also returns estimated salaries; the salary analysis excludes them so conclusions are not driven by model guesses.
- **Official APIs only.** No scraping of sites whose terms prohibit it.
- **Idempotent runs.** Re-running the pipeline updates existing postings instead of duplicating them, and tracks `first_seen_at` / `last_seen_at`.

## Data sources

All sources are official, publicly documented APIs.

| Source | What it gives | Used for |
|---|---|---|
| [Adzuna API](https://developer.adzuna.com/) | Broad market coverage, salaries, **JD snippet only** | Hiring volume, who is hiring, salaries, trends |
| Greenhouse / Lever / Ashby job boards | **Full job descriptions** from selected Canadian employers (`config/search.yaml`) | Accurate skill demand (`skill_demand_full_jd`) |

## Limitations

- **Snippets undercount skills.** Adzuna returns the first part of a JD, so skills listed later are missed. Skill shares are therefore reported separately for full-JD postings.
- **Full-JD sample skews to tech and fintech.** Large banks and many enterprises use applicant systems without a public API, so they appear in hiring-volume data (via Adzuna) but not in the full-JD skill analysis.
- **Recruitment agencies.** Agency postings are flagged (`config/staffing_agencies.yaml`) and excluded from employer rankings; the agency list is maintained by hand.
- **Trends need history.** The early-warning signal becomes meaningful after several weekly runs.
- `data/sample/sample_jobs.json` is **synthetic** (fictional companies), generated by `scripts/make_sample_data.py`, and exists only for the demo and tests.

## Roadmap

See [docs/ROADMAP.md](docs/ROADMAP.md): resume matching and scoring (Phase 2), a prompt chain for tailored applications (Phase 3), and a web MVP (Phase 4).

## Author

Hansel Tung · Master of Management Analytics candidate, Smith School of Business, Queen's University
