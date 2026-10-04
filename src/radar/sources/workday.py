"""Workday career sites (used by most large Canadian banks, insurers and retailers).

Each company's public career site is backed by the JSON endpoints the page itself calls:
  search:  POST https://{host}/wday/cxs/{tenant}/{site}/jobs
  detail:  GET  https://{host}/wday/cxs/{tenant}/{site}{externalPath}

These are not a documented public API, so this module is deliberately polite:
  * checks the site's robots.txt first and skips the site if it disallows access
    (or if robots.txt cannot be read)
  * one request per second, a capped number of pages per search term
  * downloads full details only for postings not already in the database
"""
from __future__ import annotations

import time
import urllib.robotparser
from dataclasses import dataclass, field

import requests

HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "User-Agent": "canada-job-market-radar (personal labour-market research; low volume)",
}
PAGE_SIZE = 20  # Workday's maximum per search page
RETRIES = 2          # extra attempts after a timeout or dropped connection
RETRY_WAIT = 5.0     # seconds, doubled on each retry


def _with_retry(call, sleep, *args, **kwargs):
    """Retry transient network failures (timeouts, resets); other errors pass through."""
    wait = RETRY_WAIT
    for attempt in range(RETRIES + 1):
        try:
            resp = call(*args, **kwargs)
            if getattr(resp, "status_code", 200) in (429, 502, 503, 504) and attempt < RETRIES:
                sleep(wait); wait *= 2
                continue
            return resp
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            if attempt == RETRIES:
                raise
            sleep(wait); wait *= 2


@dataclass
class WorkdayResult:
    new_jobs: list[dict] = field(default_factory=list)      # normalized, full description
    seen_known_ids: set[str] = field(default_factory=set)   # already in DB, still listed
    skipped_reason: str = ""


def job_id_for(tenant: str, path: str) -> str:
    # externalPath ends with a unique slug, e.g. /job/Toronto-Ontario/Analyst_R_1511869
    return f"workday_{tenant}_{path.rstrip('/').rsplit('/', 1)[-1]}"


def robots_allows(host: str, paths: list[str], session=requests) -> tuple[bool, str]:
    try:
        resp = session.get(f"https://{host}/robots.txt", headers={"User-Agent": HEADERS["User-Agent"]},
                           timeout=20)
    except Exception as exc:  # network problem: be conservative
        return False, f"robots.txt unreachable ({exc.__class__.__name__})"
    if resp.status_code >= 500 or resp.status_code in (401, 403):
        return False, f"robots.txt returned {resp.status_code}"
    if resp.status_code >= 400:  # no robots.txt means no restrictions
        return True, ""
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(resp.text.splitlines())
    for path in paths:
        if not rp.can_fetch(HEADERS["User-Agent"], f"https://{host}{path}"):
            return False, f"robots.txt disallows {path}"
    return True, ""


def fetch_workday(
    host: str,
    tenant: str,
    site: str,
    company: str,
    search_terms: list[str],
    title_keywords: list[str],
    known_ids: set[str],
    location_keywords: list[str] | None = None,
    max_pages_per_term: int = 3,
    max_new_details: int = 80,
    pause: float = 1.0,
    session=requests,
    sleep=time.sleep,
) -> WorkdayResult:
    result = WorkdayResult()
    base = f"https://{host}/wday/cxs/{tenant}/{site}"
    ok, reason = robots_allows(host, [f"/{site}/", f"/wday/cxs/{tenant}/{site}/jobs"], session)
    if not ok:
        result.skipped_reason = reason
        return result

    kws = [k.lower() for k in title_keywords]
    locs = [k.lower() for k in location_keywords or []]

    def location_ok(text: str) -> bool:
        text = (text or "").lower()
        # "3 Locations" hides the cities, so keep it and let the full posting decide
        return not locs or "location" in text or any(k in text for k in locs)

    paths: dict[str, str] = {}  # externalPath -> title
    for term in search_terms:
        for page in range(max_pages_per_term):
            body = {"appliedFacets": {}, "limit": PAGE_SIZE, "offset": page * PAGE_SIZE, "searchText": term}
            resp = _with_retry(session.post, sleep, f"{base}/jobs", json=body, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            postings = resp.json().get("jobPostings") or []
            sleep(pause)
            for p in postings:
                title, path = p.get("title", ""), p.get("externalPath", "")
                if (path and (not kws or any(k in title.lower() for k in kws))
                        and location_ok(p.get("locationsText", ""))):
                    paths[path] = title
            if len(postings) < PAGE_SIZE:
                break

    for path in paths:
        jid = job_id_for(tenant, path)
        if jid in known_ids:
            result.seen_known_ids.add(jid)
            continue
        if len(result.new_jobs) >= max_new_details:
            break  # the rest are picked up on the next run
        resp = _with_retry(session.get, sleep, f"{base}{path}", headers=HEADERS, timeout=30)
        sleep(pause)
        if resp.status_code != 200:
            continue
        info = (resp.json() or {}).get("jobPostingInfo") or {}
        if info:
            result.new_jobs.append(normalize_workday(info, company, tenant, path))
    return result


def normalize_workday(info: dict, company: str, tenant: str, path: str) -> dict:
    locations = [info.get("location") or ""] + list(info.get("additionalLocations") or [])
    return {
        "job_id": job_id_for(tenant, path),
        "source": "workday",
        "title": info.get("title", ""),
        "company": company,
        "location": " / ".join(loc for loc in locations if loc),
        "province": "",
        "description": info.get("jobDescription", "") or "",
        "salary_min": None,
        "salary_max": None,
        "salary_is_predicted": 0,
        "category": "",
        "contract_time": info.get("timeType", "") or "",
        "posted_at": info.get("startDate", "") or "",
        "url": info.get("externalUrl", "") or "",
        "search_query": "",
    }
