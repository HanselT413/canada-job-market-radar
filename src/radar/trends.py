"""Skill trend early-warning: which skills are growing fastest in new postings.

Method
------
1. Take each posting's publish date.
2. For each skill, compute its share of postings published in the recent window
   (default: last 14 days) and in the window before it (the 14 days before that).
3. Report the change in percentage points, the relative change, and a
   two-proportion z-test so small-sample noise is not flagged as a trend.
4. Adjust for testing many skills at once (Benjamini-Hochberg, FDR 10%):
   RISING / FALLING = survives the correction; WATCH = p < 0.05 only.

Caveat: on a first run, older postings are only those still open, so the earlier
window under-represents roles that filled quickly. Running the radar daily removes
that bias over time, because postings are stored when they first appear.
"""
from __future__ import annotations

import math
import sqlite3

import pandas as pd


def load_postings(conn: sqlite3.Connection, where: str = "", params: tuple = ()) -> tuple[pd.DataFrame, pd.DataFrame]:
    jobs = pd.read_sql(f"SELECT job_id, posted_at FROM jobs WHERE posted_at <> '' {where}", conn, params=params)
    skills = pd.read_sql("SELECT job_id, skill FROM job_skills", conn)
    jobs["posted_at"] = pd.to_datetime(jobs["posted_at"], utc=True, errors="coerce", format="mixed")
    jobs = jobs.dropna(subset=["posted_at"])
    # Monday of the posting's week, as a plain date
    jobs["week"] = (jobs["posted_at"].dt.tz_localize(None).dt.to_period("W-SUN").dt.start_time.dt.date)
    return jobs, skills


def weekly_skill_share(conn: sqlite3.Connection) -> pd.DataFrame:
    """Share of each week's new postings that mention each skill (for a trend line chart)."""
    jobs, skills = load_postings(conn)
    totals = jobs.groupby("week").size().rename("week_postings")
    merged = skills.merge(jobs[["job_id", "week"]], on="job_id")
    counts = merged.groupby(["week", "skill"]).size().rename("postings").reset_index()
    counts = counts.merge(totals, left_on="week", right_index=True)
    counts["share_pct"] = (100 * counts["postings"] / counts["week_postings"]).round(1)
    return counts.sort_values(["week", "skill"]).reset_index(drop=True)


def _two_prop_z(x1: int, n1: int, x2: int, n2: int) -> float:
    """Two-sided p-value for H0: p1 == p2."""
    if n1 == 0 or n2 == 0:
        return float("nan")
    p = (x1 + x2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    if se == 0:
        return float("nan")
    z = (x1 / n1 - x2 / n2) / se
    return math.erfc(abs(z) / math.sqrt(2))


def skill_trends(
    conn: sqlite3.Connection,
    window_days: int = 14,
    min_mentions: int = 5,
    alpha: float = 0.05,
    fdr: float = 0.10,
    industry: str | None = None,
) -> pd.DataFrame:
    """Compare each skill's share in the latest window vs the window before it.
    Optionally restricted to one industry."""
    where, params = ("AND industry = ?", (industry,)) if industry else ("", ())
    jobs, skills = load_postings(conn, where, params)
    if jobs.empty:
        return pd.DataFrame()

    # Windows end at the newest posting date, so a late or missed run doesn't shift them
    end = jobs["posted_at"].max()
    recent_start = end - pd.Timedelta(days=window_days)
    prior_start = end - pd.Timedelta(days=2 * window_days)
    jobs["window"] = None
    jobs.loc[jobs["posted_at"] > recent_start, "window"] = "recent"
    jobs.loc[(jobs["posted_at"] > prior_start) & (jobs["posted_at"] <= recent_start), "window"] = "prior"
    jobs = jobs.dropna(subset=["window"])
    n = jobs.groupby("window").size()
    n_recent, n_prior = int(n.get("recent", 0)), int(n.get("prior", 0))

    merged = skills.merge(jobs[["job_id", "window"]], on="job_id")
    counts = merged.pivot_table(index="skill", columns="window", values="job_id",
                                aggfunc="count", fill_value=0)
    for col in ("recent", "prior"):
        if col not in counts:
            counts[col] = 0

    rows = []
    for skill, r in counts.iterrows():
        x_recent, x_prior = int(r["recent"]), int(r["prior"])
        if x_recent + x_prior < min_mentions:
            continue
        share_recent = 100 * x_recent / n_recent if n_recent else 0.0
        share_prior = 100 * x_prior / n_prior if n_prior else 0.0
        p_value = _two_prop_z(x_recent, n_recent, x_prior, n_prior)
        change_pp = share_recent - share_prior
        rows.append({
            "skill": skill,
            "prior_share_pct": round(share_prior, 1),
            "recent_share_pct": round(share_recent, 1),
            "change_pp": round(change_pp, 1),
            "relative_change_pct": round(100 * change_pp / share_prior, 1) if share_prior else None,
            "p_value": round(p_value, 4),
            "recent_mentions": x_recent,
            "prior_mentions": x_prior,
        })

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    # Testing many skills at once inflates false positives, so control the
    # false discovery rate with Benjamini-Hochberg q-values.
    out["q_value"] = _bh_qvalues(out["p_value"].tolist())
    out["signal"] = [
        ("RISING" if c > 0 else "FALLING") if q < fdr
        else ("WATCH" if p < alpha else "stable")
        for c, p, q in zip(out["change_pp"], out["p_value"], out["q_value"])
    ]
    cols = ["skill", "prior_share_pct", "recent_share_pct", "change_pp", "relative_change_pct",
            "p_value", "q_value", "signal", "recent_mentions", "prior_mentions"]
    out = out[cols]
    out.attrs.update(n_recent=n_recent, n_prior=n_prior, window_days=window_days,
                     recent=(recent_start.date(), end.date()), prior=(prior_start.date(), recent_start.date()))
    return out.sort_values("change_pp", ascending=False).reset_index(drop=True)


def _bh_qvalues(pvals: list[float]) -> list[float]:
    """Benjamini-Hochberg adjusted p-values (q-values)."""
    m = len(pvals)
    order = sorted(range(m), key=lambda i: pvals[i])
    q = [0.0] * m
    running = 1.0
    for rank in range(m, 0, -1):
        i = order[rank - 1]
        running = min(running, pvals[i] * m / rank)
        q[i] = round(min(running, 1.0), 4)
    return q


def skill_trends_by_industry(conn: sqlite3.Connection, min_postings: int = 40, **kwargs) -> pd.DataFrame:
    """Run skill_trends separately for each industry with enough postings."""
    counts = pd.read_sql(
        "SELECT industry, COUNT(*) AS n FROM jobs WHERE posted_at <> '' GROUP BY industry", conn)
    frames = []
    for industry in counts.loc[counts["n"] >= min_postings, "industry"]:
        t = skill_trends(conn, industry=industry, **kwargs)
        if not t.empty:
            frames.append(t.assign(industry=industry))
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    return out[["industry"] + [c for c in out.columns if c != "industry"]]
