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
from radar.db import ROOT, connect, load_named_queries, upsert_jobs
from radar.skills import SkillExtractor

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


def collect_live(config: dict) -> list[dict]:
    from radar.sources.adzuna import fetch_adzuna, normalize_adzuna
    from radar.sources.ats import fetch_greenhouse, fetch_lever, normalize_greenhouse, normalize_lever

    jobs: list[dict] = []
    az = config.get("adzuna") or {}
    for query in az.get("queries", []):
        raw = list(fetch_adzuna(query, az.get("where", "Toronto"), az.get("pages_per_query", 2),
                                max_days_old=az.get("max_days_old", 30)))
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
    return jobs


def filter_location(jobs: list[dict], keywords: list[str]) -> list[dict]:
    if not keywords:
        return jobs
    kws = [k.lower() for k in keywords]
    return [j for j in jobs if any(k in (j.get("location") or "").lower() for k in kws)]


def run_fetch(db_path: Path, sample: bool) -> None:
    config = yaml.safe_load((ROOT / "config" / "search.yaml").read_text())
    if sample:
        jobs = json.loads(SAMPLE_PATH.read_text())
        print(f"Loaded {len(jobs)} sample postings")
    else:
        load_env()
        print("Fetching live postings...")
        jobs = collect_live(config)

    jobs = filter_location(jobs, config.get("location_filter") or [])
    jobs = clean_jobs(jobs)
    extractor = SkillExtractor()
    skills = {j["job_id"]: extractor.extract(f"{j['title']} {j['description']}") for j in jobs}

    db_path.parent.mkdir(parents=True, exist_ok=True)
    with connect(db_path) as conn:
        n = upsert_jobs(conn, jobs, skills)
        total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    print(f"Saved {n} postings after cleaning; database now holds {total}")


def run_export(db_path: Path, out_dir: Path = EXPORT_DIR) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
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
    print(f"Exports written to {out_dir}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="radar")
    parser.add_argument("command", choices=["fetch", "export"])
    parser.add_argument("--sample", action="store_true", help="use bundled sample data (no API key)")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args(argv)

    if args.command == "fetch":
        run_fetch(args.db, args.sample)
    else:
        run_export(args.db)
    return 0


if __name__ == "__main__":
    sys.exit(main())
