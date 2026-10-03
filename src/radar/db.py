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
    "seniority", "role_family", "is_staffing_agency", "full_description", "posted_at", "url", "search_query", "dedupe_key",
]


NEW_COLUMNS = {"is_staffing_agency": "INTEGER DEFAULT 0", "full_description": "INTEGER DEFAULT 0"}


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
