"""Hook-pattern classification and cooldown.

The account's catalogue was 59% ``Stop Saying ___`` titles, and 44% of it was
the single pattern ``Stop Saying "Very ___"`` - fifteen variants of one joke.
A follower who sees three in a row stops registering the fourth, and 64 reels
only carried 34 distinct lessons.

Avoiding repeated *topics* was already handled by the history file. This adds
the missing layer: avoiding a repeated *hook shape*, regardless of topic.
"""
from __future__ import annotations

import re

#: (family slug, human description, matcher). Order matters - first match wins,
#: so the narrow "very" case is tested before the general "stop saying".
_FAMILIES: tuple[tuple[str, str, re.Pattern], ...] = (
    ("stop-saying-very", 'Stop Saying "Very ___"',
     re.compile(r"^\s*stop\s+saying\s+['\"]?very\b", re.I)),
    ("stop-saying", 'Stop Saying "___"',
     re.compile(r"^\s*stop\s+saying\b", re.I)),
    ("stop-confusing", "Stop Confusing These Words",
     re.compile(r"^\s*stop\s+confusing\b", re.I)),
    ("percent-hype", '"X% Fail This" / "Only X% Get This"',
     re.compile(r"\b\d{1,3}\s*%|\bonly\s+\d+\b", re.I)),
    ("textbook-vs-native", "Textbook vs Native",
     re.compile(r"\btextbook\b.*\bvs\b|\bvs\b.*\bnative\b", re.I)),
    ("challenge", "Quick English Challenge",
     re.compile(r"\bchallenge\b|\bquiz\b|\btest\b", re.I)),
    ("how-to-sound", "How to Sound ___",
     re.compile(r"^\s*how\s+to\s+sound\b", re.I)),
    ("dont-say", "Don't Say ___",
     re.compile(r"^\s*(don'?t|never)\s+say\b", re.I)),
)

#: Alternative shapes offered to the model when a family is on cooldown.
ALTERNATIVE_HOOKS: tuple[str, ...] = (
    "A mistake warning: 'You're using this word wrong'",
    "A contrarian claim: 'Fluent speakers avoid this common phrase'",
    "A situation hook: 'In a job interview, never say this'",
    "A comparison: 'These two words are not interchangeable'",
    "A curiosity gap: 'There is a word for this feeling'",
    "A direct question: 'Which one would you say here?'",
    "A confession: 'I used this word wrong for years'",
    "A list tease: 'Three phrases that instantly sound natural'",
)

OTHER = "other"

#: How many recent posts a family stays on cooldown for.
COOLDOWN = 5


def hook_family(title: str) -> str:
    """Classify a title into a hook family slug (``other`` if unrecognised)."""
    text = str(title or "").strip()
    if not text:
        return OTHER
    for slug, _label, pattern in _FAMILIES:
        if pattern.search(text):
            return slug
    return OTHER


def describe(slug: str) -> str:
    """Human-readable description of a family, for the prompt."""
    for family, label, _pattern in _FAMILIES:
        if family == slug:
            return label
    return slug


def recent_families(titles: list[str], limit: int = COOLDOWN) -> list[str]:
    """Families used in the most recent ``limit`` titles, newest first.

    ``other`` is excluded: it is a catch-all, not a pattern worth banning.
    """
    seen: list[str] = []
    for title in reversed(list(titles or [])[-limit:]):
        family = hook_family(title)
        if family != OTHER and family not in seen:
            seen.append(family)
    return seen


def is_on_cooldown(title: str, titles: list[str], limit: int = COOLDOWN) -> bool:
    """True if ``title`` reuses a hook shape from the recent window."""
    family = hook_family(title)
    return family != OTHER and family in recent_families(titles, limit)


def avoid_clause(titles: list[str], limit: int = COOLDOWN) -> str:
    """Prompt fragment banning recently used hook shapes."""
    families = recent_families(titles, limit)
    if not families:
        return ""
    banned = "; ".join(describe(slug) for slug in families)
    alternatives = "\n".join(f"  - {shape}" for shape in ALTERNATIVE_HOOKS)
    return (
        "HOOK VARIETY (hard requirement):\n"
        f"These title patterns were used in the last {limit} posts and are BANNED "
        f"for this one: {banned}.\n"
        "Do not produce a title matching any of them, even with a different topic.\n"
        "Use a different shape, for example:\n"
        f"{alternatives}\n"
    )
