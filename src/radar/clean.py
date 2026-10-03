"""Cleaning and enrichment: strip HTML, tag seniority and role family, dedupe."""
from __future__ import annotations

import re

TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")

SENIORITY_RULES = [
    ("intern", r"\b(intern|internship|co-?op|student)\b"),
    ("new_grad", r"\b(new grad|graduate program|entry[- ]level|junior|jr\.?|associate)\b"),
    ("senior", r"\b(senior|sr\.?|lead|principal|staff)\b"),
    ("manager", r"\b(manager|director|head of|vp)\b"),
]

ROLE_FAMILY_RULES = [
    ("product_analyst", r"product analy"),
    ("data_scientist", r"data scien|machine learning|\bml\b"),
    ("bi_analyst", r"\bbi\b|business intelligence|reporting analy"),
    ("risk_aml_analyst", r"\brisk\b|\baml\b|anti[- ]money|fraud|financial crime|compliance"),
    ("business_analyst", r"business analy|business systems"),
    ("data_analyst", r"data analy|analytics|insights? analy"),
]


def strip_html(text: str) -> str:
    text = TAG_RE.sub(" ", text or "")
    return SPACE_RE.sub(" ", text).strip()


def tag_seniority(title: str) -> str:
    t = (title or "").lower()
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


def dedupe_key(job: dict) -> str:
    """Same title + company + city counts as one posting across sources."""
    parts = [job.get("title", ""), job.get("company", ""), (job.get("location") or "").split(",")[0]]
    return "|".join(re.sub(r"[^a-z0-9]", "", p.lower()) for p in parts)


def clean_jobs(jobs: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out = []
    for job in jobs:
        job = dict(job)
        job["description"] = strip_html(job.get("description", ""))
        job["title"] = SPACE_RE.sub(" ", job.get("title", "")).strip()
        job["seniority"] = tag_seniority(job["title"])
        job["role_family"] = tag_role_family(job["title"])
        key = dedupe_key(job)
        if key in seen:
            continue
        seen.add(key)
        job["dedupe_key"] = key
        out.append(job)
    return out
