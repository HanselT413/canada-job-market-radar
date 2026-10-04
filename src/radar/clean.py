"""Cleaning and enrichment: strip HTML, tag seniority and role family, dedupe."""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml

AGENCY_PATH = Path(__file__).resolve().parents[2] / "config" / "staffing_agencies.yaml"
TARGETS_PATH = Path(__file__).resolve().parents[2] / "config" / "target_companies.yaml"

TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")

SENIORITY_RULES = [
    ("intern", r"\b(intern|internship|co-?op|student)\b"),
    ("new_grad", r"\b(new grad|graduate program|entry[- ]level|junior|jr\.?|associate)\b"),
    ("senior", r"\b(senior|sr\.?|lead|principal|staff)\b"),
    ("manager", r"\b(manager|director|head of|vp)\b"),
]

# Order matters: the first matching rule wins.
ROLE_FAMILY_RULES = [
    ("product_analyst", r"product analy"),
    ("product_manager", r"product manag|product owner|product associate|associate product|\bapm\b"
                        r"|product lead|head of product|director,? (of )?product|product operations"),
    ("data_scientist", r"data scien|machine learning|\bml\b"),
    ("sales_analyst", r"sales analy|sales operations|sales ops|revenue operations|\brevops\b"
                      r"|commercial analy|pricing analy|sales strategy analy"),
    ("insights_analyst", r"insights?\b|client analy|customer analy|consumer analy|marketing analy"
                         r"|customer experience analy|\bcx analy|client experience analy"),
    ("bi_analyst", r"\bbi\b|business intelligence|reporting analy"),
    ("aml_compliance", r"\baml\b|anti[- ]money|\bkyc\b|financial crimes?|sanctions|fraud"
                       r"|transaction monitoring|compliance|\bcdd\b|\bedd\b"),
    ("risk_analyst", r"\brisk\b"),
    ("business_analyst", r"business analy|business systems"),
    ("data_analyst", r"data analy|analytics|insights? analy"),
]

# Titles where "manager" names the role, not people management
IC_MANAGER_TITLES = re.compile(r"product manager|program manager|project manager|account manager"
                               r"|relationship manager|case manager")


def strip_html(text: str) -> str:
    text = TAG_RE.sub(" ", text or "")
    return SPACE_RE.sub(" ", text).strip()


def tag_seniority(title: str) -> str:
    t = IC_MANAGER_TITLES.sub(" ", (title or "").lower())
    for label, pattern in SENIORITY_RULES:
        if re.search(pattern, t):
            return label
    return "mid"


def tag_role_family(title: str) -> str:
    t = (title or "").lower()
    for label, pattern in ROLE_FAMILY_RULES:
        if re.search(pattern, t):
            return label
    return "other"


@lru_cache(maxsize=1)
def _agency_rules(path: str = str(AGENCY_PATH)) -> tuple[frozenset, tuple]:
    data = yaml.safe_load(Path(path).read_text()) or {}
    names = frozenset(n.lower().strip() for n in data.get("names") or [])
    keywords = tuple(k.lower() for k in data.get("keywords") or [])
    return names, keywords


def is_staffing_agency(company: str) -> int:
    name = (company or "").lower().strip()
    if not name:
        return 0
    names, keywords = _agency_rules()
    return int(name in names or any(k in name for k in keywords))


@lru_cache(maxsize=1)
def _target_rules(path: str = str(TARGETS_PATH)) -> tuple:
    """(tier, compiled pattern) pairs; tier 1 is checked first."""
    if not Path(path).exists():
        return ()
    data = yaml.safe_load(Path(path).read_text()) or {}
    rules = []
    for tier_key, tier in (("tier1", 1), ("tier2", 2)):
        for name, aliases in (data.get(tier_key) or {}).items():
            names = [name] + list(aliases or [])
            alt = "|".join(re.escape(n.lower()) for n in names)
            rules.append((tier, re.compile(rf"(?<![a-z0-9])(?:{alt})(?![a-z0-9])")))
    return tuple(rules)


def target_tier(company: str) -> int:
    name = (company or "").lower()
    for tier, pattern in _target_rules():
        if pattern.search(name):
            return tier
    return 0


def dedupe_key(job: dict) -> str:
    """Same title + company + city counts as one posting across sources."""
    parts = [job.get("title", ""), job.get("company", ""), (job.get("location") or "").split(",")[0]]
    return "|".join(re.sub(r"[^a-z0-9]", "", p.lower()) for p in parts)


def clean_jobs(jobs: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out = []
    # Company boards first, so a full job description wins over an Adzuna snippet
    for job in sorted(jobs, key=lambda j: j.get("source") == "adzuna"):
        job = dict(job)
        job["description"] = strip_html(job.get("description", ""))
        job["title"] = SPACE_RE.sub(" ", job.get("title", "")).strip()
        job["seniority"] = tag_seniority(job["title"])
        job["role_family"] = tag_role_family(job["title"])
        job["is_staffing_agency"] = is_staffing_agency(job.get("company", ""))
        job["target_tier"] = target_tier(job.get("company", ""))
        # Adzuna returns a snippet; company boards return the full job description
        job["full_description"] = int(job.get("source") != "adzuna")
        key = dedupe_key(job)
        if key in seen:
            continue
        seen.add(key)
        job["dedupe_key"] = key
        out.append(job)
    return out
