"""SQLite storage: upsert jobs and skills, run named analysis queries."""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "sql" / "schema.sql"
ANALYSIS_PATH = ROOT / "sql" / "analysis.sql"

JOB_COLUMNS = [
    "job_id", "source", "title", "company", "location", "province", "description",
    "salary_min", "salary_max", "salary_is_predicted", "category", "contract_time",
    "seniority", "role_family", "is_staffing_agency", "full_description", "target_tier", "industry", "posted_at", "url", "search_query", "dedupe_key",
]


NEW_COLUMNS = {"is_staffing_agency": "INTEGER DEFAULT 0", "full_description": "INTEGER DEFAULT 0",
               "target_tier": "INTEGER DEFAULT 0", "industry": "TEXT DEFAULT 'Unclassified'"}


def connect(db_path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_PATH.read_text())
    # Upgrade databases created by an earlier version of the schema
    existing = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
    for col, decl in NEW_COLUMNS.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} {decl}")
    return conn


def upsert_jobs(conn: sqlite3.Connection, jobs: list[dict], skills: dict[str, list[tuple[str, str]]]) -> int:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cols = ", ".join(JOB_COLUMNS + ["first_seen_at", "last_seen_at"])
    placeholders = ", ".join(["?"] * (len(JOB_COLUMNS) + 2))
    updates = ", ".join(f"{c}=excluded.{c}" for c in JOB_COLUMNS if c != "job_id")
    sql = (
        f"INSERT INTO jobs ({cols}) VALUES ({placeholders}) "
        f"ON CONFLICT(job_id) DO UPDATE SET {updates}, last_seen_at=excluded.last_seen_at"
    )
    for job in jobs:
        conn.execute(sql, [job.get(c) for c in JOB_COLUMNS] + [now, now])
        conn.execute("DELETE FROM job_skills WHERE job_id = ?", (job["job_id"],))
        conn.executemany(
            "INSERT INTO job_skills (job_id, skill_group, skill) VALUES (?, ?, ?)",
            [(job["job_id"], g, s) for g, s in skills.get(job["job_id"], [])],
        )
    conn.commit()
    return len(jobs)


def load_named_queries(path: Path = ANALYSIS_PATH) -> dict[str, str]:
    """Split analysis.sql on '-- name: xxx' headers."""
    text = path.read_text()
    parts = re.split(r"^-- name:\s*(\w+)\s*$", text, flags=re.MULTILINE)
    return {parts[i]: parts[i + 1].strip() for i in range(1, len(parts), 2)}


def known_job_ids(conn: sqlite3.Connection, prefix: str = "") -> set[str]:
    rows = conn.execute("SELECT job_id FROM jobs WHERE job_id LIKE ?", (prefix + "%",))
    return {r[0] for r in rows}


def touch_seen(conn: sqlite3.Connection, job_ids: set[str]) -> None:
    """Mark postings that are still listed without downloading them again."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn.executemany("UPDATE jobs SET last_seen_at = ? WHERE job_id = ?", [(now, j) for j in job_ids])
    conn.commit()


def retag_all(conn: sqlite3.Connection, extractor) -> int:
    """Re-apply the current tagging rules and skill dictionary to every stored posting,
    so edits to config files (skills, target companies, industries) reach old rows too."""
    from radar.clean import is_staffing_agency, tag_industry, tag_role_family, tag_seniority, target_tier

    rows = conn.execute("SELECT job_id, title, company, description FROM jobs").fetchall()
    conn.executemany(
        "UPDATE jobs SET seniority = ?, role_family = ?, is_staffing_agency = ?, target_tier = ?, "
        "industry = ? WHERE job_id = ?",
        [(tag_seniority(t), tag_role_family(t), is_staffing_agency(c), target_tier(c), tag_industry(c), j)
         for j, t, c, _ in rows],
    )
    conn.execute("DELETE FROM job_skills")
    conn.executemany(
        "INSERT INTO job_skills (job_id, skill_group, skill) VALUES (?, ?, ?)",
        [(j, g, sk) for j, t, _, d in rows for g, sk in extractor.extract(f"{t} {d or ''}")],
    )
    conn.commit()
    return len(rows)
