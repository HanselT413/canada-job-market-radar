"""Ontario job-posting rules (in force January 1, 2026) — how postings line up with them.

Since 2026-01-01, Ontario employers with more than 25 employees must, in publicly
advertised job postings:
  * state the expected pay or a pay range; the range may not exceed $50,000 a year
    (not required when pay is above $200,000 a year)
  * say whether the posting is for an existing vacancy
  * disclose if artificial intelligence is used to screen, assess or select applicants
  * not require "Canadian experience"

This module is separate from the core pipeline: it only reads the jobs table and
writes its own table (posting_rules) and CSV exports. Deleting it changes nothing else.

Scope and honesty notes
  * Only postings with a FULL job description are checked (Adzuna snippets are not).
  * Only Ontario locations and postings published on/after 2026-01-01.
  * Employer size is not known; the employers tracked here are large.
  * Detection is automated text matching and can miss wording it was not built for.
    Results say "not detected", never "non-compliant".
"""
from __future__ import annotations

import re
import sqlite3

import pandas as pd

RULES_START = "2026-01-01"
RANGE_CAP = 50_000
HIGH_PAY_EXEMPTION = 200_000
HOURS_PER_YEAR = 2080

ONTARIO_PLACES = re.compile(
    r"ontario|toronto|mississauga|ottawa|waterloo|kitchener|markham|brampton|oakville"
    r"|hamilton|vaughan|richmond hill|burlington|guelph",
    re.IGNORECASE,
)
# "London, ON" or "Canada - Remote (ON, AB)"; case-sensitive so "on call" never matches
ONTARIO_ABBR = re.compile(r"[,(/]\s*ON\b")


def is_ontario(location: str) -> bool:
    location = location or ""
    return bool(ONTARIO_PLACES.search(location) or ONTARIO_ABBR.search(location))

_NUM = r"(\d{1,3}(?:[,\s]\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*([kK])?"
SALARY_RANGE = re.compile(
    rf"\$\s*{_NUM}\s*(?:CAD|CDN|C\$)?\s*(?:-|–|—|to|and)\s*\$?\s*{_NUM}"
    r"(?:\s*(?:CAD|CDN))?(?P<tail>[^.\n]{0,40})",
    re.IGNORECASE,
)
# Ranges written without "$" but introduced by a pay word, e.g. "Salary range: 75,000 - 95,000"
SALARY_RANGE_WORDED = re.compile(
    rf"(?:salary|pay|compensation|base)[^.\n$]{{0,30}}?\b{_NUM}\s*(?:-|–|—|to)\s*{_NUM}(?P<tail>[^.\n]{{0,40}})",
    re.IGNORECASE,
)
HOURLY = re.compile(r"per hour|/\s*h(ou)?r|hourly|an hour", re.IGNORECASE)

SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
AI_TERM = re.compile(r"artificial intelligence|\bAI\b|automated (decision|screening)|machine learning", re.IGNORECASE)
AI_ACTION = re.compile(r"screen|assess|evaluat|review|select|rank|shortlist|filter", re.IGNORECASE)
AI_OBJECT = re.compile(r"applica|candidate|resume|résumé|\bCVs?\b|submission", re.IGNORECASE)
AI_NEGATION = re.compile(r"\b(do(es)? not|don't|doesn't|not|no)\b[^.]{0,40}\b(use|using|used)\b"
                         r"|\bwithout (the use of )?(ai|artificial intelligence)", re.IGNORECASE)

VACANCY_EXISTING = re.compile(
    r"(is|for|represents|fill) an? (existing|current|active) (vacancy|position|opening|role)"
    r"|existing vacancy|current vacancy|this (is a|position is a) (current|existing) (opening|vacancy)",
    re.IGNORECASE)
VACANCY_NOT_EXISTING = re.compile(
    r"not (for )?an? (existing|current) (vacancy|position|opening)|talent (pool|pipeline|community)"
    r"|future (opportunities|openings|vacancies)|evergreen|pipeline (requisition|posting)",
    re.IGNORECASE)
CANADIAN_EXPERIENCE = re.compile(r"canadian (work |job )?experience", re.IGNORECASE)
CANADIAN_EXPERIENCE_NOT_REQUIRED = re.compile(
    r"(no|not|without)\b[^.]{0,30}canadian (work |job )?experience|canadian (work |job )?experience"
    r"[^.]{0,30}(is )?not (required|necessary)", re.IGNORECASE)


def _to_number(value: str, k: str | None) -> float:
    n = float(re.sub(r"[,\s]", "", value))
    return n * 1000 if k else n


def detect_salary(text: str) -> dict:
    """First plausible pay range in the text, annualized. Empty dict if none."""
    text = text or ""
    matches = list(SALARY_RANGE.finditer(text)) + list(SALARY_RANGE_WORDED.finditer(text))
    for m in sorted(matches, key=lambda m: m.start()):
        lo, hi = _to_number(m.group(1), m.group(2)), _to_number(m.group(3), m.group(4) or m.group(2))
        if hi < lo:
            lo, hi = hi, lo
        context = text[max(0, m.start() - 40): m.end()]
        hourly = bool(HOURLY.search(context)) or hi < 300
        if hourly:
            lo, hi = lo * HOURS_PER_YEAR, hi * HOURS_PER_YEAR
        if 20_000 <= lo <= 1_000_000 and lo < hi <= 2_000_000:
            return {"salary_min": lo, "salary_max": hi, "salary_period": "hourly" if hourly else "annual"}
    return {}


def detect_ai_disclosure(text: str) -> str:
    """'uses_ai', 'no_ai' (states AI is not used) or 'none' (no statement found)."""
    for sentence in SENTENCE_SPLIT.split(text or ""):
        if AI_TERM.search(sentence) and AI_ACTION.search(sentence) and AI_OBJECT.search(sentence):
            return "no_ai" if AI_NEGATION.search(sentence) else "uses_ai"
    return "none"


def detect_vacancy(text: str) -> str:
    """'existing', 'not_existing' (talent pool / future roles) or 'none'."""
    if VACANCY_NOT_EXISTING.search(text or ""):
        return "not_existing"
    if VACANCY_EXISTING.search(text or ""):
        return "existing"
    return "none"


def detect_canadian_experience(text: str) -> bool:
    text = text or ""
    return bool(CANADIAN_EXPERIENCE.search(text)) and not CANADIAN_EXPERIENCE_NOT_REQUIRED.search(text)


def check_posting(description: str) -> dict:
    salary = detect_salary(description)
    width = (salary["salary_max"] - salary["salary_min"]) if salary else None
    return {
        "salary_range_found": int(bool(salary)),
        "salary_min": salary.get("salary_min"),
        "salary_max": salary.get("salary_max"),
        "salary_period": salary.get("salary_period"),
        "salary_range_width": width,
        # None when no range found or when pay is above the exemption threshold
        "range_within_cap": (None if not salary or salary["salary_min"] > HIGH_PAY_EXEMPTION
                             else int(width <= RANGE_CAP)),
        "ai_disclosure": detect_ai_disclosure(description),
        "vacancy_statement": detect_vacancy(description),
        "canadian_experience_required": int(detect_canadian_experience(description)),
    }


def build_posting_rules(conn: sqlite3.Connection) -> pd.DataFrame:
    """Check every in-scope posting and store the result in the posting_rules table."""
    jobs = pd.read_sql(
        "SELECT job_id, company, industry, role_family, location, posted_at, description, target_tier "
        "FROM jobs WHERE full_description = 1", conn)
    if jobs.empty:
        return pd.DataFrame()
    posted = pd.to_datetime(jobs["posted_at"], utc=True, errors="coerce", format="mixed")
    in_scope = jobs["location"].map(is_ontario) & (posted >= pd.Timestamp(RULES_START, tz="UTC"))
    jobs = jobs[in_scope].copy()
    if jobs.empty:
        conn.execute("DROP TABLE IF EXISTS posting_rules")
        return pd.DataFrame()

    checks = pd.DataFrame([check_posting(d) for d in jobs["description"]], index=jobs.index)
    result = pd.concat([jobs.drop(columns=["description", "posted_at"]), checks], axis=1)
    for col in ("range_within_cap", "salary_range_width", "salary_min", "salary_max"):
        result[col] = pd.to_numeric(result[col], errors="coerce")
    result.to_sql("posting_rules", conn, if_exists="replace", index=False)
    return result


def summarize(result: pd.DataFrame, by: str | None = None, min_postings: int = 5) -> pd.DataFrame:
    """Share of postings with each element, overall or per company / industry."""
    if result.empty:
        return pd.DataFrame()
    df = result.assign(
        ai_statement=result["ai_disclosure"] != "none",
        vacancy_statement_found=result["vacancy_statement"] != "none",
    )
    groups = df.groupby(by) if by else df.groupby(lambda _: "All Ontario postings checked")
    out = groups.agg(
        postings=("job_id", "count"),
        pct_salary_range=("salary_range_found", "mean"),
        pct_range_within_cap=("range_within_cap", "mean"),
        pct_ai_statement=("ai_statement", "mean"),
        pct_vacancy_statement=("vacancy_statement_found", "mean"),
        pct_canadian_experience=("canadian_experience_required", "mean"),
        median_range_width=("salary_range_width", "median"),
    )
    pct_cols = [c for c in out.columns if c.startswith("pct_")]
    out[pct_cols] = (out[pct_cols] * 100).round(1)
    out = out[out["postings"] >= min_postings] if by else out
    return out.sort_values("postings", ascending=False).reset_index().rename(columns={"index": by or "scope"})
