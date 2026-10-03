# Roadmap

Each phase is a self-contained, demoable milestone that can be pushed to GitHub on its own.

## Phase 1 — Market data pipeline ✅
- Adzuna + Greenhouse + Lever collection, cleaning, dedupe
- Dictionary-based skill extraction
- SQLite storage and six analysis queries
- CSV exports and a Tableau Public dashboard (skill demand, salary by skill, top employers)

**Deliverable:** live dashboard link in the README + a short "what I found" write-up.

## Phase 2 — Resume parsing and match scoring
- `src/radar/resume.py`: PDF/DOCX → structured master profile (JSON)
- Two-stage matching:
  1. Recall: embedding similarity between profile and every posting
  2. Precision: rubric scoring on the top 20 only (keeps LLM cost low)
- 100-point rubric, every score backed by a quote from the resume:

| Dimension | Points |
|---|---|
| Skills match | 40 |
| Relevant experience | 25 |
| Education / certifications | 15 |
| Industry background | 10 |
| Location / work eligibility | 10 |

- Skill-gap report: which in-demand skills (from Phase 1 data) the resume lacks

## Phase 3 — Prompt chain
Versioned templates live in `prompts/`. Each step returns JSON that matches a schema.

1. Resume parse → profile JSON
2. JD parse → requirements, keywords, auto-detected direction (operations / analyst / AML / manager)
3. Match score → rubric scores with evidence
4. Gap analysis → missing skills and learning suggestions
5. Resume tailoring → tagline, summary, competencies, skills line; option to keep original experience bullets word-for-word
6. Cover letter → role title stated clearly, tied to the JD with specific numbers
7. Interview prep → likely questions + STAR answers from real experience

Guardrails: outputs may only cite facts in the master profile; JD text is treated as data, never as instructions; keywords the profile cannot support are flagged instead of inserted.

## Phase 4 — Web MVP
- Streamlit app: upload resume → ranked matches → one-click tailored package
- Application tracker and funnel dashboard
- Pilot with 10 classmates; track activation, 7-day retention, and interviews obtained (North Star)
- Privacy: resumes stored locally or encrypted; aligned with PIPEDA
