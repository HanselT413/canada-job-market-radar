import json
import sqlite3

from radar.clean import clean_jobs, strip_html, tag_role_family, tag_seniority
from radar.db import load_named_queries
from radar.pipeline import SAMPLE_PATH, filter_location, run_export, run_fetch
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
    assert tag_role_family("AML Analyst") == "risk_aml_analyst"
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
    assert {p.stem for p in out.glob("*.csv")} == set(load_named_queries())
