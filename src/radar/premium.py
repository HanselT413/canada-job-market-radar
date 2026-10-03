"""Skill salary premium: how much more do postings that ask for a skill pay,
after controlling for seniority, role family, and city?

Model (OLS, robust HC3 standard errors):

    log(salary_mid) = b0 + sum_k b_k * has_skill_k
                         + seniority dummies + role_family dummies + city dummies + e

premium_k = exp(b_k) - 1   ->  "postings asking for skill k pay ~X% more,
                                holding seniority, role and city constant"

Interpretation: this is a controlled association, not a causal effect.
Employers who ask for a skill may differ in ways the model does not see
(company size, industry, team). Only employer-posted salaries are used.
"""
from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd
import statsmodels.api as sm

CONTROLS = ["seniority", "role_family", "city"]


def load_salary_frame(conn: sqlite3.Connection) -> tuple[pd.DataFrame, list[str]]:
    jobs = pd.read_sql(
        """
        SELECT job_id, seniority, role_family, location,
               (salary_min + salary_max) / 2.0 AS salary_mid
        FROM jobs
        WHERE salary_min IS NOT NULL AND salary_max IS NOT NULL
          AND salary_is_predicted = 0
          AND salary_min > 20000 AND salary_max < 400000   -- drop hourly/typo values
        """,
        conn,
    )
    skills = pd.read_sql("SELECT job_id, skill FROM job_skills", conn)
    jobs["city"] = jobs["location"].fillna("").str.split(",").str[0].str.strip().replace("", "Unknown")
    skill_matrix = (
        skills[skills["job_id"].isin(jobs["job_id"])]
        .assign(v=1)
        .pivot_table(index="job_id", columns="skill", values="v", fill_value=0)
    )
    df = jobs.merge(skill_matrix, left_on="job_id", right_index=True, how="left").fillna(
        {c: 0 for c in skill_matrix.columns}
    )
    return df, list(skill_matrix.columns)


def skill_premiums(
    conn: sqlite3.Connection,
    min_with: int = 10,
    min_without: int = 10,
) -> tuple[pd.DataFrame, dict]:
    """Return (per-skill premium table, model summary dict)."""
    df, skill_cols = load_salary_frame(conn)
    if df.empty:
        return pd.DataFrame(), {"n": 0}

    # Keep skills with enough postings both with and without them, otherwise b_k is noise
    usable = [s for s in skill_cols if min_with <= df[s].sum() <= len(df) - min_without]
    if not usable:
        return pd.DataFrame(), {"n": len(df), "note": "not enough salary data per skill yet"}

    controls = pd.get_dummies(df[CONTROLS], drop_first=True, dtype=float)
    X = pd.concat([df[usable].astype(float), controls], axis=1)
    X = X.loc[:, X.std() > 0]  # drop constant columns
    X = sm.add_constant(X)
    y = np.log(df["salary_mid"])
    model = sm.OLS(y, X).fit(cov_type="HC3")

    ci = model.conf_int()
    rows = []
    for s in usable:
        if s not in model.params:
            continue
        b = model.params[s]
        rows.append({
            "skill": s,
            "premium_pct": round(100 * (np.exp(b) - 1), 1),
            "ci_low_pct": round(100 * (np.exp(ci.loc[s, 0]) - 1), 1),
            "ci_high_pct": round(100 * (np.exp(ci.loc[s, 1]) - 1), 1),
            "p_value": round(float(model.pvalues[s]), 4),
            "significant": bool(model.pvalues[s] < 0.05),
            "postings_with_skill": int(df[s].sum()),
        })
    table = pd.DataFrame(rows).sort_values("premium_pct", ascending=False).reset_index(drop=True)
    summary = {
        "n": int(model.nobs),
        "r_squared": round(float(model.rsquared), 3),
        "skills_tested": len(table),
        "controls": CONTROLS,
    }
    return table, summary
