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
    expected = set(load_named_queries()) | {"skill_share_by_week", "skill_trends", "skill_premiums",
                                            "skill_trends_by_industry", "ontario_rules_summary",
                                            "ontario_rules_by_industry", "ontario_rules_by_company"}
    assert {p.stem for p in out.glob("*.csv")} == expected


def test_bh_qvalues():
    q = _bh_qvalues([0.01, 0.04, 0.03, 0.5])
    assert q == [0.04, 0.0533, 0.0533, 0.5]


def test_analysis_recovers_planted_signals(tmp_path):
    """Sample data plants: dbt demand rising, dbt ~+10% and Python ~+6% salary premium."""
    db = tmp_path / "radar.db"
    run_fetch(db, sample=True)
    conn = sqlite3.connect(db)

    # The sample spreads a slow rise over 12 weeks, so use 4-week windows to test the method
    trends = skill_trends(conn, window_days=28).set_index("skill")
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


def test_target_tier():
    from radar.clean import target_tier
    assert target_tier("The Toronto-Dominion Bank") == 1
    assert target_tier("Royal Bank of Canada") == 1
    assert target_tier("Tim Hortons") == 2          # alias of Restaurant Brands International
    assert target_tier("Mackenzie Health") == 0     # hospital, not Mackenzie Investments
    assert target_tier("TDL Group") == 0            # "TD" must match as a whole word
    assert target_tier("") == 0


def test_search_config_is_valid():
    cfg = yaml.safe_load(open("config/search.yaml"))
    for b in cfg["workday"]:
        assert set(b) == {"host", "tenant", "site", "company"}
        assert b["host"].startswith(b["tenant"] + ".") and b["host"].endswith(".myworkdayjobs.com")
    keys = [(b["host"], b["site"]) for b in cfg["workday"]]
    assert len(keys) == len(set(keys))


def test_industry_and_ai_tags():
    from radar.clean import tag_industry
    assert tag_industry("TD Bank") == "Banking"
    assert tag_industry("Wealthsimple") == "Fintech & Payments"
    assert tag_industry("Tim Hortons") == "Retail & Consumer Goods"
    assert tag_industry("Unknown Co") == "Unclassified"
    ex = SkillExtractor()
    found = {s for _, s in ex.extract("Use generative AI, ChatGPT and AI agents; build RAG on a vector database")}
    assert {"Generative AI / LLMs", "AI Tools (ChatGPT, Copilot)", "AI Agents / Automation",
            "RAG / Vector Search", "AI (any mention)"} <= found
    assert not ex.extract("A prompt response to client requests")  # 'prompt' alone is not prompt engineering


def test_trend_windows_use_days(tmp_path):
    """Recent = last N days, prior = the N days before; older postings are ignored."""
    from radar.db import connect, upsert_jobs
    db = tmp_path / "t.db"
    base = {"source": "workday", "company": "X", "description": ""}
    jobs, skills = [], {}
    for i in range(40):
        day = i % 40  # spread over 40 days before 2026-10-01
        jid = f"j{i}"
        jobs.append(dict(base, job_id=jid, title="Analyst", posted_at=f"2026-{9 if day < 30 else 8}-{(30 - day) if day < 30 else (61 - day):02d}T00:00:00Z"))
        # dbt only in the last 14 days
        skills[jid] = [("modern", "dbt")] if day < 14 else [("technical", "SQL")]
    with connect(db) as conn:
        upsert_jobs(conn, jobs, skills)
        t = skill_trends(conn, window_days=14, min_mentions=1).set_index("skill")
        assert t.attrs["n_recent"] == 14 and t.attrs["n_prior"] == 14
        assert t.loc["dbt", "recent_share_pct"] == 100.0 and t.loc["dbt", "prior_share_pct"] == 0.0


def test_ontario_rules_detection():
    from radar.ontario_rules import check_posting, is_ontario
    r = check_posting("Pay Details: $64,000 - $88,000 CAD. This posting is for an existing vacancy. "
                      "We use artificial intelligence (AI) to screen and assess applications.")
    assert (r["salary_min"], r["salary_max"], r["range_within_cap"]) == (64000, 88000, 1)
    assert r["ai_disclosure"] == "uses_ai" and r["vacancy_statement"] == "existing"
    wide = check_posting("The base salary range is $85K–$140K.")
    assert wide["salary_range_width"] == 55000 and wide["range_within_cap"] == 0
    assert check_posting("Pay: $25.00 to $31.50 per hour.")["salary_period"] == "hourly"
    assert check_posting("Salary: $210,000 - $290,000")["range_within_cap"] is None   # above exemption
    assert check_posting("We do not use AI to screen applicants.")["ai_disclosure"] == "no_ai"
    assert check_posting("A team of 2,000 - 3,000 people.")["salary_range_found"] == 0  # not pay
    assert check_posting("Canadian experience required.")["canadian_experience_required"] == 1
    assert check_posting("No Canadian experience required.")["canadian_experience_required"] == 0
    assert check_posting("Join our talent pool for future opportunities.")["vacancy_statement"] == "not_existing"
    assert is_ontario("London, ON") and is_ontario("Canada - Remote (ON, AB)")
    assert not is_ontario("Remote, on call") and not is_ontario("Vancouver, BC")


def test_ontario_rules_end_to_end(tmp_path):
    from radar.db import connect, upsert_jobs
    from radar.ontario_rules import build_posting_rules, summarize
    base = {"source": "workday", "company": "TD Bank", "industry": "Banking", "full_description": 1,
            "title": "Data Analyst", "role_family": "data_analyst"}
    jobs = [
        dict(base, job_id="a", location="Toronto, Ontario", posted_at="2026-09-01",
             description="Pay: $70,000 - $90,000. This is an existing vacancy."),
        dict(base, job_id="b", location="Toronto, Ontario", posted_at="2026-09-02", description="Great team."),
        dict(base, job_id="c", location="Vancouver, BC", posted_at="2026-09-02", description="Pay: $1 - $2"),
        dict(base, job_id="d", location="Toronto, Ontario", posted_at="2025-12-01", description="old"),
        dict(base, job_id="e", source="adzuna", full_description=0, location="Toronto, Ontario",
             posted_at="2026-09-02", description="snippet"),
    ]
    with connect(tmp_path / "t.db") as conn:
        upsert_jobs(conn, jobs, {})
        result = build_posting_rules(conn)
        assert sorted(result["job_id"]) == ["a", "b"]   # Ontario, full JD, posted 2026+
        overall = summarize(result).iloc[0]
        assert overall["postings"] == 2 and overall["pct_salary_range"] == 50.0
        assert overall["pct_vacancy_statement"] == 50.0


def test_retag_updates_old_rows(tmp_path):
    """Rows stored before a rule existed pick up new tags and skills on the next run."""
    from radar.db import connect, retag_all, upsert_jobs
    old = {"job_id": "old1", "source": "lever", "title": "Product Manager", "company": "Wealthsimple",
           "location": "Toronto", "description": "Experience with generative AI and dbt",
           "role_family": "other", "industry": "Unclassified", "target_tier": 0}
    with connect(tmp_path / "t.db") as conn:
        upsert_jobs(conn, [old], {"old1": []})
        retag_all(conn, SkillExtractor())
        row = conn.execute("SELECT role_family, industry, target_tier FROM jobs").fetchone()
        assert row == ("product_manager", "Fintech & Payments", 1)
        skills = {r[0] for r in conn.execute("SELECT skill FROM job_skills")}
        assert {"Generative AI / LLMs", "dbt"} <= skills
