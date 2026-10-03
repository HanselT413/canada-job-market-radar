"""Dictionary-based skill extraction from job descriptions.

Phase 1 uses transparent regex matching so every tag can be explained.
Phase 2 can add embeddings / LLM extraction on top.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

DEFAULT_SKILLS_PATH = Path(__file__).resolve().parents[2] / "config" / "skills.yaml"


class SkillExtractor:
    def __init__(self, path: Path = DEFAULT_SKILLS_PATH):
        data = yaml.safe_load(Path(path).read_text())
        self.patterns: list[tuple[str, str, re.Pattern]] = []
        for group, skills in data.items():
            for skill, aliases in skills.items():
                joined = "|".join(f"(?:{a})" for a in aliases)
                pattern = re.compile(rf"(?<![a-z0-9])(?:{joined})(?![a-z0-9])", re.IGNORECASE)
                self.patterns.append((group, skill, pattern))

    def extract(self, text: str) -> list[tuple[str, str]]:
        """Return sorted unique (skill_group, skill) pairs found in text."""
        text = text or ""
        found = {(group, skill) for group, skill, p in self.patterns if p.search(text)}
        return sorted(found)
