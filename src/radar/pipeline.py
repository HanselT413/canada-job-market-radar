"""Command-line pipeline.

    python -m radar.pipeline fetch            # live: Adzuna + Greenhouse + Lever
    python -m radar.pipeline fetch --sample   # offline demo with data/sample/sample_jobs.json
    python -m radar.pipeline export           # run sql/analysis.sql, write CSVs for Tableau
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

import yaml

from radar.clean import clean_jobs
from radar.db import (JOB_COLUMNS, ROOT, connect, known_job_ids, load_named_queries, touch_seen,
                      upsert_jobs)
from radar.premium import skill_premiums
from radar.skills import SkillExtractor
from radar.trends import skill_trends, skill_trends_by_industry, weekly_skill_share

DEFAULT_DB = ROOT / "data" / "radar.db"
SAMPLE_PATH = ROOT / "data" / "sample" / "sample_jobs.json"
EXPORT_DIR = ROOT / "data" / "exports"


def load_env(path: Path = ROOT / ".env") -> None:
    """Minimal .env loader (KEY=VALUE lines) so no extra dependency is needed."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"'))


def collect_live(config: dict, known_ids: set[str] | None = None) -> tuple[list[dict], set[str]]:
    """Return (postings, ids of already-stored postings that are still listed)."""
    from radar.sources.adzuna import fetch_adzuna, normalize_adzuna
    from radar.sources.ats import (fetch_ashby, fetch_greenhouse, fetch_lever, normalize_ashby,
                                  normalize_greenhouse, normalize_lever)

    jobs: list[dict] = []
    az = config.get("adzuna") or {}
    for query in az.get("queries", []):
        try:
            raw = list(fetch_adzuna(query, az.get("where", "Toronto"), az.get("pages_per_query", 2),
                                    max_days_old=az.get("max_days_old", 30),
                                    title_only=az.get("title_only", True)))
        except Exception as exc:  # e.g. 429 rate limit: keep going with the other queries
            print(f"  adzuna '{query}': skipped ({exc})")
            continue
        jobs += [normalize_adzuna(r, query) for r in raw]
        print(f"  adzuna '{query}': {len(raw)}")

    for board in config.get("greenhouse") or []:
        try:
            raw = fetch_greenhouse(board["token"])
            jobs += [normalize_greenhouse(r, board["company"]) for r in raw]
            print(f"  greenhouse {board['company']}: {len(raw)}")
        except Exception as exc:  # one bad board should not stop the run
            print(f"  greenhouse {board['company']}: skipped ({exc})")

    for board in config.get("lever") or []:
        try:
            raw = fetch_lever(board["company"])
            jobs += [normalize_lever(r, board.get("display", board["company"])) for r in raw]
            print(f"  lever {board['company']}: {len(raw)}")
        except Exception as exc:
            print(f"  lever {board['company']}: skipped ({exc})")

    for board in config.get("ashby") or []:
        try:
            raw = fetch_ashby(board["org"])
            jobs += [normalize_ashby(r, board["company"]) for r in raw]
            print(f"  ashby {board['company']}: {len(raw)}")
        except Exception as exc:
            print(f"  ashby {board['company']}: skipped ({exc})")

    still_listed: set[str] = set()
    wd = config.get("workday_settings") or {}
    for board in config.get("workday") or []:
        try:
            from radar.sources.workday import fetch_workday
            res = fetch_workday(
                board["host"], board["tenant"], board["site"], board["company"],
                search_terms=wd.get("search_terms", ["analyst"]),
                title_keywords=config.get("ats_title_filter") or [],
                known_ids=known_ids or set(),
                location_keywords=config.get("location_filter") or [],
                max_pages_per_term=wd.get("max_pages_per_term", 3),
                max_new_details=wd.get("max_new_details", 80),
            )
            if res.skipped_reason:
                print(f"  workday {board['company']}: skipped ({res.skipped_reason})")
                continue
            jobs += res.new_jobs
            still_listed |= res.seen_known_ids
            print(f"  workday {board['company']}: {len(res.new_jobs)} new, "
                  f"{len(res.seen_known_ids)} already stored")
        except Exception as exc:
            print(f"  workday {board['company']}: skipped ({exc})")
    return jobs, still_listed


def filter_location(jobs: list[dict], keywords: list[str]) -> list[dict]:
    if not keywords:
        return jobs
    kws = [k.lower() for k in keywords]
    return [j for j in jobs if any(k in (j.get("location") or "").lower() for k in kws)]


def filter_ats_titles(jobs: list[dict], keywords: list[str]) -> list[dict]:
    """Company boards list all roles; keep analytics-type titles. Adzuna rows pass through."""
    if not keywords:
        return jobs
    kws = [k.lower() for k in keywords]
    return [j for j in jobs
            if j.get("source") == "adzuna" or any(k in (j.get("title") or "").lower() for k in kws)]


def run_fetch(db_path: Path, sample: bool) -> None:
    config = yaml.safe_load((ROOT / "config" / "search.yaml").read_text())
    still_listed: set[str] = set()
    if sample:
        jobs = json.loads(SAMPLE_PATH.read_text())
        print(f"Loaded {len(jobs)} sample postings")
    else:
        load_env()
        print("Fetching live postings...")
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with connect(db_path) as conn:
            known = known_job_ids(conn, "workday_")
        jobs, still_listed = collect_live(config, known)

    jobs = filter_ats_titles(jobs, config.get("ats_title_filter") or [])
    jobs = filter_location(jobs, config.get("location_filter") or [])
    jobs = clean_jobs(jobs)
    extractor = SkillExtractor()
    skills = {j["job_id"]: extractor.extract(f"{j['title']} {j['description']}") for j in jobs}

    db_path.parent.mkdir(parents=True, exist_ok=True)
    with connect(db_path) as conn:
        n = upsert_jobs(conn, jobs, skills)
        touch_seen(conn, still_listed)
        total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    print(f"Saved {n} postings after cleaning; database now holds {total}")


def run_export(db_path: Path, out_dir: Path = EXPORT_DIR) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    config = yaml.safe_load((ROOT / "config" / "search.yaml").read_text())
    window_days = (config.get("trends") or {}).get("window_days", 14)
    with connect(db_path) as conn:
        for name, sql in load_named_queries().items():
            cur = conn.execute(sql)
            headers = [d[0] for d in cur.description]
            rows = cur.fetchall()
            with open(out_dir / f"{name}.csv", "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(headers)
                writer.writerows(rows)
            print(f"  {name}.csv ({len(rows)} rows)")

        weekly = weekly_skill_share(conn)
        weekly.to_csv(out_dir / "skill_share_by_week.csv", index=False)
        print(f"  skill_share_by_week.csv ({len(weekly)} rows)")

        trends = skill_trends(conn, window_days=window_days)
        trends.to_csv(out_dir / "skill_trends.csv", index=False)
        rising = trends[trends["signal"] == "RISING"]["skill"].tolist() if not trends.empty else []
        print(f"  skill_trends.csv ({len(trends)} rows, last {window_days} days vs the {window_days} before) "
              f"| rising: {', '.join(rising) or 'none yet'}")

        by_industry = skill_trends_by_industry(conn, window_days=window_days)
        by_industry.to_csv(out_dir / "skill_trends_by_industry.csv", index=False)
        print(f"  skill_trends_by_industry.csv ({len(by_industry)} rows)")

        premiums, summary = skill_premiums(conn)
        premiums.to_csv(out_dir / "skill_premiums.csv", index=False)
        print(f"  skill_premiums.csv ({len(premiums)} rows) | model n={summary.get('n')}, "
              f"R²={summary.get('r_squared', 'n/a')}")
    print(f"Exports written to {out_dir}")


def _mysql_value(value):
    """Format one value for MySQL LOAD DATA: NULL as \\N, ISO timestamps as DATETIME."""
    if value is None or value == "":
        return r"\N"
    if isinstance(value, str) and len(value) >= 19 and value[4] == "-" and value[10] == "T":
        return value[:19].replace("T", " ")
    return value


def run_export_tables(db_path: Path, out_dir: Path = EXPORT_DIR / "tables") -> None:
    """Dump the raw jobs and job_skills tables as CSV for loading into MySQL."""
    out_dir.mkdir(parents=True, exist_ok=True)
    with connect(db_path) as conn:
        # Explicit column order so the CSV always matches sql/mysql/load_data.sql
        tables = {
            "jobs": JOB_COLUMNS + ["first_seen_at", "last_seen_at"],
            "job_skills": ["job_id", "skill_group", "skill"],
        }
        for table, columns in tables.items():
            cur = conn.execute(f"SELECT {', '.join(columns)} FROM {table}")
            headers = [d[0] for d in cur.description]
            rows = cur.fetchall()
            with open(out_dir / f"{table}.csv", "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(headers)
                writer.writerows([_mysql_value(v) for v in row] for row in rows)
            print(f"  {table}.csv ({len(rows)} rows)")
    print(f"Table dumps written to {out_dir} — load them with sql/mysql/load_data.sql")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="radar")
    parser.add_argument("command", choices=["fetch", "export", "export-tables"])
    parser.add_argument("--sample", action="store_true", help="use bundled sample data (no API key)")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args(argv)

    if args.command == "fetch":
        run_fetch(args.db, args.sample)
    elif args.command == "export":
        run_export(args.db)
    else:
        run_export_tables(args.db)
    return 0


if __name__ == "__main__":
    sys.exit(main())
