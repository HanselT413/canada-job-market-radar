"""Adzuna job search API client (Canada).

Docs: https://developer.adzuna.com/
Note: Adzuna returns a shortened description (snippet), not the full JD.
"""
from __future__ import annotations

import os
import time
from typing import Iterator

import requests

BASE_URL = "https://api.adzuna.com/v1/api/jobs/ca/search/{page}"


def fetch_adzuna(
    what: str,
    where: str = "Toronto",
    pages: int = 2,
    results_per_page: int = 50,
    max_days_old: int = 30,
    pause: float = 2.5,   # ~24 calls/minute, under the trial plan's per-minute limit
    title_only: bool = True,
) -> Iterator[dict]:
    """Yield raw Adzuna job dicts for one search query."""
    app_id = os.environ.get("ADZUNA_APP_ID")
    app_key = os.environ.get("ADZUNA_APP_KEY")
    if not app_id or not app_key:
        raise RuntimeError("Set ADZUNA_APP_ID and ADZUNA_APP_KEY in your .env file")

    for page in range(1, pages + 1):
        params = {
            "app_id": app_id,
            "app_key": app_key,
            "what": what,
            "where": where,
            "results_per_page": results_per_page,
            "max_days_old": max_days_old,
            "content-type": "application/json",
        }
        if title_only:
            # Match keywords in the job title only. Without this, "sales analyst" also
            # returns e.g. Sales Representative or Financial Analyst ads that mention sales.
            params["title_only"] = what
            params.pop("what")
        resp = requests.get(BASE_URL.format(page=page), params=params, timeout=30)
        if resp.status_code == 400 and title_only:
            # Fall back to full-text search if the API rejects title_only
            params["what"] = params.pop("title_only")
            resp = requests.get(BASE_URL.format(page=page), params=params, timeout=30)
        resp.raise_for_status()
        results = resp.json().get("results", [])
        if not results:
            break
        yield from results
        time.sleep(pause)


def normalize_adzuna(raw: dict, query: str) -> dict:
    """Map one Adzuna result to the common job schema."""
    location = raw.get("location") or {}
    area = location.get("area") or []
    return {
        "job_id": f"adzuna_{raw.get('id')}",
        "source": "adzuna",
        "title": raw.get("title", ""),
        "company": (raw.get("company") or {}).get("display_name", ""),
        "location": location.get("display_name", ""),
        "province": area[1] if len(area) > 1 else "",
        "description": raw.get("description", ""),
        "salary_min": raw.get("salary_min"),
        "salary_max": raw.get("salary_max"),
        "salary_is_predicted": int(str(raw.get("salary_is_predicted", "0")) == "1"),
        "category": (raw.get("category") or {}).get("label", ""),
        "contract_time": raw.get("contract_time") or "",
        "posted_at": raw.get("created", ""),
        "url": raw.get("redirect_url", ""),
        "search_query": query,
    }
