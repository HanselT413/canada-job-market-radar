"""Greenhouse and Lever public job board APIs (no key needed).

Greenhouse: https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true
Lever:      https://api.lever.co/v0/postings/{company}?mode=json
"""
from __future__ import annotations

import html
from datetime import datetime, timezone

import requests

GREENHOUSE_URL = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
LEVER_URL = "https://api.lever.co/v0/postings/{company}"


def fetch_greenhouse(token: str) -> list[dict]:
    resp = requests.get(GREENHOUSE_URL.format(token=token), params={"content": "true"}, timeout=30)
    resp.raise_for_status()
    return resp.json().get("jobs", [])


def normalize_greenhouse(raw: dict, company: str) -> dict:
    return {
        "job_id": f"greenhouse_{raw.get('id')}",
        "source": "greenhouse",
        "title": raw.get("title", ""),
        "company": company,
        "location": (raw.get("location") or {}).get("name", ""),
        "province": "",
        # Greenhouse returns HTML-escaped HTML; unescape here, strip tags in clean.py
        "description": html.unescape(raw.get("content", "") or ""),
        "salary_min": None,
        "salary_max": None,
        "salary_is_predicted": 0,
        "category": "",
        "contract_time": "",
        "posted_at": raw.get("updated_at", ""),
        "url": raw.get("absolute_url", ""),
        "search_query": "",
    }


def fetch_lever(company: str) -> list[dict]:
    resp = requests.get(LEVER_URL.format(company=company), params={"mode": "json"}, timeout=30)
    resp.raise_for_status()
    return resp.json()


def normalize_lever(raw: dict, company: str) -> dict:
    created_ms = raw.get("createdAt")
    posted = (
        datetime.fromtimestamp(created_ms / 1000, tz=timezone.utc).isoformat()
        if created_ms
        else ""
    )
    categories = raw.get("categories") or {}
    return {
        "job_id": f"lever_{raw.get('id')}",
        "source": "lever",
        "title": raw.get("text", ""),
        "company": company,
        "location": categories.get("location", ""),
        "province": "",
        "description": raw.get("descriptionPlain", "") or "",
        "salary_min": None,
        "salary_max": None,
        "salary_is_predicted": 0,
        "category": categories.get("team", ""),
        "contract_time": categories.get("commitment", ""),
        "posted_at": posted,
        "url": raw.get("hostedUrl", ""),
        "search_query": "",
    }
