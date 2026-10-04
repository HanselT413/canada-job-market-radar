"""Make a spreadsheet for checking the Ontario-rules detection by hand.

    python3 scripts/make_validation_sample.py          # 50 postings (default)
    python3 scripts/make_validation_sample.py 80       # another sample size

Writes data/validation/validation_sample.csv. Open it in Excel or Numbers, read each
posting (the url column links to it; the full text is in the description column), and fill
in the four "you_" columns with 1 (present) or 0 (not present). Save as CSV with the same
name, then run notebook section "Validation" or:

    python3 scripts/make_validation_sample.py --score

The sample is stratified: half with a pay range detected, half without, so both kinds of
mistake (missed and false detections) can be measured.
"""
import sqlite3
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "radar.db"
OUT = ROOT / "data" / "validation" / "validation_sample.csv"

CHECKS = [
    # (column you fill in, program's result column, how the program's value becomes 0/1)
    ("you_salary_range", "salary_range_found", lambda v: int(v)),
    ("you_ai_statement", "ai_disclosure", lambda v: int(v != "none")),
    ("you_vacancy_statement", "vacancy_statement", lambda v: int(v != "none")),
    ("you_canadian_experience", "canadian_experience_required", lambda v: int(v)),
]


def make_sample(n: int = 50, seed: int = 42) -> pd.DataFrame:
    conn = sqlite3.connect(DB)
    rules = pd.read_sql("SELECT * FROM posting_rules", conn)
    jobs = pd.read_sql("SELECT job_id, title, url, description FROM jobs", conn)
    df = rules.merge(jobs, on="job_id")
    with_pay = df[df["salary_range_found"] == 1]
    without = df[df["salary_range_found"] == 0]
    half = n // 2
    sample = pd.concat([
        with_pay.sample(min(half, len(with_pay)), random_state=seed),
        without.sample(min(n - min(half, len(with_pay)), len(without)), random_state=seed),
    ]).sample(frac=1, random_state=seed)  # shuffle so you can't tell which half a row is from

    cols = ["job_id", "company", "title", "url"]
    out = sample[cols].copy()
    for you_col, _, _ in CHECKS:
        out[you_col] = ""          # you fill these in
    out["notes"] = ""
    # Program results are kept at the end so they don't bias your reading
    out["program_salary_min"] = sample["salary_min"]
    out["program_salary_max"] = sample["salary_max"]
    for _, prog_col, _ in CHECKS:
        out[f"program_{prog_col}"] = sample[prog_col]
    out["description"] = sample["description"].str.replace(r"<[^>]+>", " ", regex=True).str.slice(0, 30000)
    return out


def score(path: Path = OUT) -> pd.DataFrame:
    """Accuracy, precision and recall of the program against your labels."""
    df = pd.read_csv(path)
    rows = []
    for you_col, prog_col, to01 in CHECKS:
        labelled = df[pd.to_numeric(df[you_col], errors="coerce").isin([0, 1])]
        if labelled.empty:
            continue
        truth = labelled[you_col].astype(int)
        pred = labelled[f"program_{prog_col}"].map(to01)
        tp = int(((pred == 1) & (truth == 1)).sum())
        fp = int(((pred == 1) & (truth == 0)).sum())
        fn = int(((pred == 0) & (truth == 1)).sum())
        rows.append({
            "check": you_col.replace("you_", ""),
            "labelled": len(labelled),
            "accuracy_%": round(100 * (pred == truth).mean(), 1),
            "precision_%": round(100 * tp / (tp + fp), 1) if tp + fp else None,  # when it says yes, is it right?
            "recall_%": round(100 * tp / (tp + fn), 1) if tp + fn else None,     # of the real yeses, how many found?
            "false_detections": fp,
            "missed": fn,
        })
    return pd.DataFrame(rows)


if __name__ == "__main__":
    if not DB.exists():
        sys.exit("No database yet. Run: python3 -m radar.pipeline fetch, then export.")
    if "--score" in sys.argv:
        print(score().to_string(index=False))
        sys.exit(0)
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    if OUT.exists():
        sys.exit(f"{OUT} already exists; move or rename it first so your labels aren't overwritten.")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    sample = make_sample(n)
    sample.to_csv(OUT, index=False)
    print(f"Wrote {len(sample)} postings to {OUT}")
    print("Fill in the you_ columns with 1 or 0, save as CSV, then run with --score.")
