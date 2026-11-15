"""Heading normalization and the 17 section categories used in the dataset."""
from __future__ import annotations

import re

SECTION_CATEGORIES: dict[str, re.Pattern] = {
    "overview": re.compile(r"overview|about|introduction|project (?:description|summary|context)|what is|purpose|summary"),
    "setup": re.compile(r"setup|set up|install|getting started|prerequisite|quick ?start|environment|requirements|dev(?:elopment)? env"),
    "commands": re.compile(r"command|scripts|usage|how to run|running|workflow"),
    "build": re.compile(r"\bbuild"),
    "testing": re.compile(r"test|verification|validat|qa\b"),
    "lint_format": re.compile(r"lint|format|style check"),
    "architecture": re.compile(r"architecture|structure|layout|organi[sz]ation|modules|components|directory|directories|codebase|repo(?:sitory)? map|key files|tech stack|stack"),
    "code_style": re.compile(r"code style|coding|convention|style guide|guidelines|best practice|patterns|naming|standards"),
    "git_pr": re.compile(r"\bgit\b|commit|pull request|\bprs?\b|branch|review|contribut|changelog|release"),
    "security": re.compile(r"security|secret|credential|permission|safety|sensitive"),
    "deployment": re.compile(r"deploy|ci\b|ci/cd|continuous|pipeline|infra"),
    "config": re.compile(r"config|configuration|env(?:ironment)? var|settings|\.env"),
    "documentation": re.compile(r"documentation|docs\b|docstring|comments"),
    "dependencies": re.compile(r"dependenc|packages|librar"),
    "troubleshooting": re.compile(r"troubleshoot|debug|common (?:issues|problems|pitfalls)|gotcha|known issues|faq|pitfall"),
    "boundaries": re.compile(r"do not|don't|never|avoid|boundar|restriction|constraint|rules|important|critical|must"),
    "agent_workflow": re.compile(r"agent|ai\b|assistant|claude|codex|copilot|llm|workflow|when (?:you|working)|task"),
}


def normalize_heading(text: str) -> str:
    text = re.sub(r"[`*_~\[\]()]", "", text)
    text = re.sub(r"^[\W\d.]+", "", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def classify_heading(normalized: str) -> set[str]:
    return {name for name, rx in SECTION_CATEGORIES.items() if rx.search(normalized)}
