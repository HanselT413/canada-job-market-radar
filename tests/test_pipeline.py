import json

import yaml
import sqlite3

from radar.clean import clean_jobs, strip_html, tag_role_family, tag_seniority
from radar.db import load_named_queries
from radar.pipeline import SAMPLE_PATH, _mysql_value, filter_location, run_export, run_export_tables, run_fetch
from radar.premium import skill_premiums
from radar.trends import _bh_qvalues, skill_trends
from radar.skills import SkillExtractor
from radar.sources.adzuna import normalize_adzuna
from radar.sources.ats import normalize_lever


def test_strip_html():
    assert strip_html("<p>Hello <b>SQL</b></p>") == "Hello SQL"


def test_tags():
    assert tag_seniority("Junior Data Analyst") == "new_grad"
    assert tag_seniority("Senior Product Analyst") == "senior"
    assert tag_seniority("Data Analyst") == "mid"
    assert tag_role_family("Product Analyst") == "product_analyst"
    assert tag_role_family("AML Analyst") == "aml_compliance"
    assert tag_role_family("Credit Risk Analyst") == "risk_analyst"
    assert tag_role_family("Associate Product Manager") == "product_manager"
    assert tag_role_family("Client Insights Analyst") == "insights_analyst"
    assert tag_role_family("Business Insights Analyst") == "insights_analyst"
    assert tag_role_family("Sales Operations Analyst") == "sales_analyst"
    assert tag_role_family("Business Intelligence Analyst") == "bi_analyst"
    # "manager" in a product title is the role, not people management
    assert tag_seniority("Product Manager") == "mid"
    assert tag_seniority("Senior Product Manager") == "senior"
    assert tag_seniority("Associate Product Manager") == "new_grad"
    assert tag_seniority("Director of Product") == "manager"
    assert tag_role_family("Business Intelligence Analyst") == "bi_analyst"


def test_dedupe_across_sources():
    a = {"job_id": "1", "title": "Data Analyst", "company": "Acme", "location": "Toronto, ON"}
    b = {"job_id": "2", "title": "Data  Analyst", "company": "ACME", "location": "Toronto"}
    assert len(clean_jobs([a, b])) == 1


def test_skill_extraction():
    ex = SkillExtractor()
    found = {s for _, s in ex.extract("Strong SQL, Power BI and A/B testing; Python or R a plus")}
    assert {"SQL", "Power BI", "A/B Testing", "Python", "R"} <= found
    # no false positive: "R&D" should not count as the R language
    assert "R" not in {s for _, s in ex.extract("Support R&D teams")}


def test_normalizers():
    az = normalize_adzuna({"id": 9, "title": "Analyst", "company": {"display_name": "X"},
                           "location": {"display_name": "Toronto, Ontario", "area": ["Canada", "Ontario"]},
                           "salary_is_predicted": "1"}, "q")
    assert az["job_id"] == "adzuna_9" and az["province"] == "Ontario" and az["salary_is_predicted"] == 1
    lv = normalize_lever({"id": "a", "text": "Analyst", "createdAt": 1700000000000,
                          "categories": {"location": "Remote"}}, "Y")
    assert lv["posted_at"].startswith("2023-11")


def test_location_filter():
    jobs = [{"location": "Toronto, Ontario"}, {"location": "Austin, Texas"}]
    assert len(filter_location(jobs, ["toronto"])) == 1


def test_end_to_end_sample(tmp_path):
    db = tmp_path / "radar.db"
    run_fetch(db, sample=True)
    conn = sqlite3.connect(db)
    raw_count = len(json.loads(SAMPLE_PATH.read_text()))
    jobs = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    assert 0 < jobs < raw_count  # Vancouver filtered + duplicate removed
    assert conn.execute("SELECT COUNT(*) FROM job_skills").fetchone()[0] > jobs

    # re-running is idempotent
    run_fetch(db, sample=True)
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == jobs

    out = tmp_path / "exports"
    run_export(db, out)
    expected = set(load_named_queries()) | {"skill_share_by_week", "skill_trends", "skill_premiums"}
    assert {p.stem for p in out.glob("*.csv")} == expected


def test_bh_qvalues():
    q = _bh_qvalues([0.01, 0.04, 0.03, 0.5])
    assert q == [0.04, 0.0533, 0.0533, 0.5]


def test_analysis_recovers_planted_signals(tmp_path):
    """Sample data plants: dbt demand rising, dbt ~+10% and Python ~+6% salary premium."""
    db = tmp_path / "radar.db"
    run_fetch(db, sample=True)
    conn = sqlite3.connect(db)

    trends = skill_trends(conn).set_index("skill")
    assert trends.loc["dbt", "signal"] == "RISING"
    assert (trends["signal"] == "RISING").sum() == 1  # no false positives after FDR correction

    premiums, summary = skill_premiums(conn)
    premiums = premiums.set_index("skill")
    assert summary["n"] > 100
    for skill, planted in [("dbt", 10.0), ("Python", 6.0)]:
        row = premiums.loc[skill]
        assert row["significant"]
        assert row["ci_low_pct"] <= planted <= row["ci_high_pct"]


def test_mysql_export(tmp_path):
    assert _mysql_value(None) == r"\N" and _mysql_value("") == r"\N"
    assert _mysql_value("2026-09-01T12:30:00+00:00") == "2026-09-01 12:30:00"
    assert _mysql_value(85000.0) == 85000.0
    db = tmp_path / "radar.db"
    run_fetch(db, sample=True)
    run_export_tables(db, tmp_path / "tables")
    assert (tmp_path / "tables" / "jobs.csv").exists()
    assert (tmp_path / "tables" / "job_skills.csv").exists()


def test_staffing_agency_flag():
    from radar.clean import is_staffing_agency
    assert is_staffing_agency("Insight Global") == 1
    assert is_staffing_agency("Acme Staffing Solutions") == 1
    assert is_staffing_agency("TD Bank") == 0
    assert is_staffing_agency("") == 0


def test_ats_title_filter():
    from radar.pipeline import filter_ats_titles
    jobs = [
        {"source": "greenhouse", "title": "Senior Software Engineer"},
        {"source": "greenhouse", "title": "Data Analyst, Growth"},
        {"source": "adzuna", "title": "Anything"},  # Adzuna is already query-scoped
    ]
    kept = filter_ats_titles(jobs, ["analyst", "data"])
    assert [j["title"] for j in kept] == ["Data Analyst, Growth", "Anything"]


def test_ashby_normalizer():
    from radar.sources.ats import normalize_ashby
    job = normalize_ashby({"id": "x1", "title": "Analytics Engineer", "location": "Remote (Canada)",
                           "secondaryLocations": [{"location": "Toronto"}],
                           "descriptionPlain": "SQL and dbt", "publishedAt": "2026-09-30T00:00:00Z"},
                          "KOHO")
    assert job["job_id"] == "ashby_x1" and job["location"] == "Remote (Canada) / Toronto"
    assert clean_jobs([job])[0]["full_description"] == 1


def test_old_database_is_upgraded(tmp_path):
    """A database made before the new columns existed should gain them automatically."""
    from radar.db import connect
    db = tmp_path / "old.db"
    from radar.db import SCHEMA_PATH
    previous_schema = "\n".join(
        line for line in SCHEMA_PATH.read_text().splitlines()
        if "is_staffing_agency" not in line and "full_description" not in line
    )
    old = sqlite3.connect(db)
    old.executescript(previous_schema)
    old.close()
    cols = {r[1] for r in connect(db).execute("PRAGMA table_info(jobs)")}
    assert {"is_staffing_agency", "full_description"} <= cols


def test_pm_and_aml_skills():
    ex = SkillExtractor()
    pm = {s for _, s in ex.extract("Own the roadmap, write PRDs in Jira, run user research in agile sprints")}
    assert {"Roadmapping", "Requirements / PRDs", "Jira", "User Research", "Agile / Scrum"} <= pm
    aml = {s for _, s in ex.extract("KYC, transaction monitoring, sanctions, STR filing to FINTRAC; CAMS an asset")}
    assert {"KYC / CDD", "Transaction Monitoring", "Sanctions Screening", "FINTRAC / PCMLTFA",
            "Suspicious Transaction Reporting", "CAMS Certification"} <= aml
    assert not ex.extract("We screen candidates carefully")  # no false positives


def test_commercial_insight_skills():
    ex = SkillExtractor()
    found = {s for _, s in ex.extract(
        "Build customer segmentation, analyze NPS surveys, churn and sales pipeline win rates, "
        "support quota planning and pricing; measure campaign performance")}
    assert {"Customer Segmentation", "Customer Experience (NPS/CSAT)", "Survey / Market Research",
            "Churn / Customer Lifetime Value", "Sales Pipeline Analysis", "Quota / Territory Planning",
            "Pricing Analysis", "Marketing Analytics"} <= found
    # "data pipelines" must not count as a sales pipeline
    assert "Sales Pipeline Analysis" not in {s for _, s in ex.extract("Build ETL data pipelines")}


def test_adzuna_title_only_request(monkeypatch):
    """Search terms go in title_only; falls back to full-text 'what' if the API returns 400."""
    from radar.sources import adzuna

    calls = []

    class FakeResp:
        def __init__(self, status, results):
            self.status_code, self._results = status, results
        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(self.status_code)
        def json(self):
            return {"results": self._results}

    def fake_get(url, params, timeout):
        calls.append(dict(params))
        if "title_only" in params and reject_title_only:
            return FakeResp(400, [])
        return FakeResp(200, [{"id": 1}] if len(calls) <= 2 else [])

    monkeypatch.setenv("ADZUNA_APP_ID", "x")
    monkeypatch.setenv("ADZUNA_APP_KEY", "y")
    monkeypatch.setattr(adzuna.requests, "get", fake_get)
    monkeypatch.setattr(adzuna.time, "sleep", lambda s: None)

    reject_title_only = False
    list(adzuna.fetch_adzuna("sales analyst", pages=1))
    assert calls[0]["title_only"] == "sales analyst" and "what" not in calls[0]

    calls.clear()
    reject_title_only = True
    list(adzuna.fetch_adzuna("sales analyst", pages=1))
    assert calls[-1]["what"] == "sales analyst" and "title_only" not in calls[-1]


class _FakeWorkday:
    """Minimal stand-in for a Workday site: robots.txt, search and detail endpoints."""

    def __init__(self, robots="User-agent: *\nAllow: /Careers/\n", robots_status=200):
        self.robots, self.robots_status = robots, robots_status
        self.calls = []
        self.postings = [
            {"title": "Data Analyst", "externalPath": "/job/Toronto-Ontario/Data-Analyst_R_1", "locationsText": "Toronto, Ontario"},
            {"title": "Software Engineer", "externalPath": "/job/Toronto-Ontario/SWE_R_2", "locationsText": "Toronto, Ontario"},
            {"title": "AML Analyst", "externalPath": "/job/Delaware/AML_R_3", "locationsText": "Wilmington, Delaware"},
            {"title": "Product Manager", "externalPath": "/job/x/PM_R_4", "locationsText": "2 Locations"},
            {"title": "Insights Analyst", "externalPath": "/job/Toronto-Ontario/Insights_R_5", "locationsText": "Toronto, Ontario"},
        ]

    class R:
        def __init__(self, status, data=None, text=""):
            self.status_code, self._data, self.text = status, data, text
        def json(self):
            return self._data
        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(self.status_code)

    def get(self, url, headers=None, timeout=None):
        self.calls.append(("GET", url))
        if url.endswith("/robots.txt"):
            return self.R(self.robots_status, text=self.robots)
        path = url.split("/Careers", 1)[1]
        title = next(p["title"] for p in self.postings if p["externalPath"] == path)
        return self.R(200, {"jobPostingInfo": {"title": title, "location": "Toronto, ON",
                                               "jobDescription": "<p>SQL and KYC</p>",
                                               "startDate": "2026-10-01", "externalUrl": "https://x"}})

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append(("POST", url))
        return self.R(200, {"jobPostings": self.postings[json["offset"]:json["offset"] + 20]})


def _run_fake(fake, known=frozenset()):
    from radar.sources.workday import fetch_workday
    return fetch_workday("acme.wd3.myworkdayjobs.com", "acme", "Careers", "Acme",
                         search_terms=["analyst"], title_keywords=["analyst", "product manager"],
                         known_ids=set(known), location_keywords=["toronto", "ontario"],
                         session=fake, sleep=lambda s: None)


def test_workday_filters_and_normalizes():
    fake = _FakeWorkday()
    res = _run_fake(fake)
    titles = sorted(j["title"] for j in res.new_jobs)
    # SWE dropped by title, Delaware dropped by location, "2 Locations" kept for the full posting to decide
    assert titles == ["Data Analyst", "Insights Analyst", "Product Manager"]
    job = res.new_jobs[0]
    assert job["source"] == "workday" and job["job_id"].startswith("workday_acme_")
    assert clean_jobs([job])[0]["full_description"] == 1


def test_workday_skips_known_postings():
    fake = _FakeWorkday()
    res = _run_fake(fake, known={"workday_acme_Data-Analyst_R_1"})
    assert "workday_acme_Data-Analyst_R_1" in res.seen_known_ids
    detail_calls = [u for m, u in fake.calls if m == "GET" and "robots" not in u]
    assert not any("Data-Analyst_R_1" in u for u in detail_calls)  # not downloaded again


def test_workday_respects_robots():
    disallowed = _FakeWorkday(robots="User-agent: *\nDisallow: /Careers/\n")
    res = _run_fake(disallowed)
    assert res.skipped_reason and not res.new_jobs
    assert [m for m, _ in disallowed.calls] == ["GET"]  # only robots.txt was requested

    unavailable = _FakeWorkday(robots_status=503)
    assert _run_fake(unavailable).skipped_reason  # cannot check robots.txt -> skip


def test_full_description_preferred_over_snippet():
    snippet = {"job_id": "adzuna_1", "source": "adzuna", "title": "Data Analyst", "company": "TD Bank",
               "location": "Toronto, Ontario", "description": "short"}
    full = dict(snippet, job_id="workday_td_1", source="workday", description="full JD with SQL")
    kept = clean_jobs([snippet, full])
    assert [j["job_id"] for j in kept] == ["workday_td_1"]


def test_add_workday_helper(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("add_workday", "scripts/add_workday.py")
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

    assert mod.parse_workday_url("https://cibc.wd3.myworkdayjobs.com/search") == \
        {"host": "cibc.wd3.myworkdayjobs.com", "tenant": "cibc", "site": "search"}
    assert mod.parse_workday_url(
        "https://bmo.wd3.myworkdayjobs.com/en-US/External/job/Toronto/Analyst_R1")["site"] == "External"
    import pytest
    with pytest.raises(ValueError):
        mod.parse_workday_url("https://jobs.example.com/careers")

    cfg = tmp_path / "search.yaml"
    cfg.write_text("workday:\n  - {host: a.wd3.myworkdayjobs.com, tenant: a, site: S, company: A}\nworkday_settings:\n  max_pages_per_term: 3\n")
    entry = mod.parse_workday_url("https://acme.wd5.myworkdayjobs.com/Careers")
    assert mod.add_to_config(entry, "Acme", cfg) == "added"
    assert mod.add_to_config(entry, "Acme", cfg) == "already in the list"
    data = yaml.safe_load(cfg.read_text())
    assert data["workday"][-1] == {"host": "acme.wd5.myworkdayjobs.com", "tenant": "acme", "site": "Careers", "company": "Acme"}
