"""The weekly content calendar.

Picking a format at random gave a lopsided feed - the existing Reels folder is
mostly vocab and quiz. A fixed weekly rotation guarantees every format appears,
so the grid looks varied and each audience segment gets served.

Override the rotation by writing ``data/schedule.json``::

    {"rotation": {"monday": "vocab", "tuesday": "quiz", ...}}
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from reelbot.formats import (
    ALL_FORMATS,
    FORMAT_CARD,
    FORMAT_CORPORATE,
    FORMAT_MISTAKE,
    FORMAT_NATIVE,
    FORMAT_QUIZ,
    FORMAT_VOCAB,
)
from reelbot.store.jsonstore import read_json, write_json
from reelbot.store.paths import CALENDAR_FILE, SCHEDULE_FILE

log = logging.getLogger(__name__)

WEEKDAY_NAMES = (
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
)

#: One post a day. Quiz runs three times a week because the account's own
#: numbers put quizzes in three of the top four reels by views (1,188 / 530 /
#: 223 against a median of 130).
#:
#: Seven slots cannot hold quiz-three-times plus all five other formats, so the
#: Sunday slot alternates by week - see :func:`format_for`. That keeps every
#: format in circulation on a two-week cycle.
DEFAULT_ROTATION: dict[str, str] = {
    "monday": FORMAT_QUIZ,
    "tuesday": FORMAT_VOCAB,
    "wednesday": FORMAT_QUIZ,
    "thursday": FORMAT_NATIVE,
    "friday": FORMAT_QUIZ,
    "saturday": FORMAT_CARD,
    "sunday": FORMAT_CORPORATE,
}

#: Sunday alternates between these on even/odd ISO weeks.
SUNDAY_ALTERNATES: tuple[str, str] = (FORMAT_CORPORATE, FORMAT_MISTAKE)


def load_rotation() -> dict[str, str]:
    """The active rotation, with any user overrides applied and validated."""
    rotation = dict(DEFAULT_ROTATION)
    raw = read_json(SCHEDULE_FILE, {})
    override = raw.get("rotation") if isinstance(raw, dict) else None

    if isinstance(override, dict):
        for day, format_key in override.items():
            key = str(day).strip().lower()
            if key not in WEEKDAY_NAMES:
                log.warning("Ignoring unknown day %r in schedule.json", day)
                continue
            if format_key not in ALL_FORMATS:
                log.warning("Ignoring unknown format %r for %s", format_key, key)
                continue
            rotation[key] = format_key

    return rotation


def save_rotation(rotation: dict[str, str]) -> None:
    write_json(SCHEDULE_FILE, {"rotation": rotation})


def format_for(day: date | None = None) -> str:
    """Which format is scheduled for ``day`` (default: today).

    Sunday alternates between the two lower-volume formats by ISO week parity,
    so both stay in circulation without giving up a quiz slot. An explicit
    Sunday override in ``data/schedule.json`` disables the alternation.
    """
    day = day or date.today()
    weekday = WEEKDAY_NAMES[day.weekday()]
    rotation = load_rotation()

    if weekday == "sunday" and rotation["sunday"] == DEFAULT_ROTATION["sunday"]:
        return SUNDAY_ALTERNATES[day.isocalendar().week % 2]
    return rotation[weekday]


def upcoming(days: int = 7, start: date | None = None) -> list[tuple[date, str]]:
    """The next ``days`` scheduled posts as ``(date, format)`` pairs."""
    start = start or date.today()
    return [
        (start + timedelta(days=offset), format_for(start + timedelta(days=offset)))
        for offset in range(days)
    ]


# --- Run log -------------------------------------------------------------

def load_log() -> list[dict]:
    raw = read_json(CALENDAR_FILE, [])
    if isinstance(raw, dict):
        raw = raw.get("runs", [])
    return [entry for entry in raw if isinstance(entry, dict)]


def record_run(day: date, format_key: str, title: str, item_id: str) -> None:
    """Note that a reel was generated for ``day``."""
    entries = load_log()
    entries.append(
        {
            "date": day.isoformat(),
            "format": format_key,
            "title": title,
            "queue_id": item_id,
        }
    )
    write_json(CALENDAR_FILE, entries[-400:])


def already_ran(day: date | None = None) -> dict | None:
    """The log entry for ``day`` if one exists.

    Task Scheduler can fire a missed task on wake, so the daily job checks this
    to avoid generating two reels for the same date.
    """
    target = (day or date.today()).isoformat()
    for entry in reversed(load_log()):
        if entry.get("date") == target:
            return entry
    return None
