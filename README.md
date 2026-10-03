# Canada Job Market Radar

A data pipeline and analytics project that tracks the Canadian job market for analytics roles, and the foundation for an AI-powered resume-to-job matching product.

**Question it answers:** *What skills does the Toronto analytics job market actually ask for, which ones pay more, and who is hiring?*

## What it does (Phase 1)

```
Adzuna API ─┐
Greenhouse ─┼─► normalize ─► clean & dedupe ─► skill extraction ─► SQLite ─► SQL analysis ─► CSV ─► Tableau
Lever ──────┘
```

| Step | File | What happens |
|---|---|---|
| Collect | `src/radar/sources/` | Pulls postings from the Adzuna Canada API and public Greenhouse / Lever job boards |
| Normalize | `normalize_*` functions | Maps each source to one common schema |
| Clean | `src/radar/clean.py` | Strips HTML, tags seniority and role family, removes cross-source duplicates |
| Extract skills | `src/radar/skills.py`, `config/skills.yaml` | Transparent dictionary matching (SQL, Python, A/B testing, AML, ...) |
| Store | `sql/schema.sql` | `jobs` and `job_skills` tables (one-to-many) |
| Analyze | `sql/analysis.sql` | Skill demand, skills by role, salary by skill, top employers, seniority mix, weekly trend |
| Export | `pipeline.py export` | One CSV per query, ready for Tableau |

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

Edit `config/search.yaml` to change search terms, city, or target companies, and `config/skills.yaml` to add skills. No code changes needed.

## Design decisions

- **Rules before AI for skill tagging.** Every tag is explainable and free to compute; LLM extraction is layered on in Phase 2.
- **Employer-posted salaries only.** Adzuna also returns estimated salaries; the salary analysis excludes them so conclusions are not driven by model guesses.
- **Official APIs only.** No scraping of sites whose terms prohibit it.
- **Idempotent runs.** Re-running the pipeline updates existing postings instead of duplicating them, and tracks `first_seen_at` / `last_seen_at`.

## Data notes

- `data/sample/sample_jobs.json` is **synthetic** (fictional companies) and exists only for the demo and tests.
- Adzuna returns a shortened description, so skill counts from Adzuna are a lower bound.

## Roadmap

See [docs/ROADMAP.md](docs/ROADMAP.md): resume matching and scoring (Phase 2), a prompt chain for tailored applications (Phase 3), and a web MVP (Phase 4).

## Author

Hansel Tung · Master of Management Analytics candidate, Smith School of Business, Queen's University
