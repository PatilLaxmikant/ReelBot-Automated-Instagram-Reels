"""Curated fallback lessons used when Gemini is unavailable.

The lessons themselves live in ``fallback_lessons.json`` beside this module.

Selection is least-recently-used, not random. With a random pick over a pool of
one - which is what four of the six formats had - every fallback was the same
lesson, and the account posted "Stop Saying 'Very Busy'" whenever the API was
down. LRU means the pool is exhausted before anything repeats, and the thing
that comes back first is the thing posted longest ago.

Matching is on :func:`reelbot.store.history.subject`, so a curated lesson is
considered used when the account has posted the same topic under a different
title.
"""
from __future__ import annotations

import copy
import functools
import json
import logging
import random
from pathlib import Path

from reelbot.formats import ALL_FORMATS, FORMAT_VOCAB
from reelbot.store import history as history_store

log = logging.getLogger(__name__)

_LESSON_FILE = Path(__file__).with_name("fallback_lessons.json")


@functools.lru_cache(maxsize=1)
def _lessons() -> dict[str, list[dict]]:
    with open(_LESSON_FILE, "r", encoding="utf-8") as handle:
        return json.load(handle)


def available_formats() -> list[str]:
    return [key for key in ALL_FORMATS if _lessons().get(key)]


def pool_size(format_key: str) -> int:
    """How many curated lessons exist for ``format_key``."""
    return len(_lessons().get(format_key) or [])


def _recency_rank(lesson: dict, history: list[str]) -> int:
    """Position of this lesson's most recent use in ``history``.

    ``-1`` means never used, which sorts first. Otherwise a higher index means
    used more recently, so it sorts last.
    """
    keys = history_store.lesson_keys(lesson)
    for position in range(len(history) - 1, -1, -1):
        if history_store.matches_any(history_store.subject(history[position]), keys):
            return position
    return -1


def pick(format_key: str | None = None, history: list[str] | None = None) -> dict:
    """Return the curated lesson this account has gone longest without using.

    The returned dict is a deep copy, so callers may mutate it freely.
    """
    if not format_key or format_key not in ALL_FORMATS:
        format_key = random.choice(available_formats() or [FORMAT_VOCAB])

    pool = _lessons().get(format_key) or _lessons()[FORMAT_VOCAB]
    # Falling back to the full account memory matters: a caller that passes
    # nothing would otherwise re-post whatever the pool happens to list first.
    titles = list(history if history is not None else history_store.used_titles())

    ranked = sorted(pool, key=lambda lesson: _recency_rank(lesson, titles))
    unused = [lesson for lesson in ranked if _recency_rank(lesson, titles) < 0]
    # Random only among never-used lessons, so consecutive fallbacks are not
    # predictable. Once the pool is exhausted, strictly oldest-first.
    chosen = copy.deepcopy(random.choice(unused) if unused else ranked[0])
    chosen["format"] = format_key

    # Curated lessons predate the send CTA, so fill it in the same way the
    # generator does for a model response that omits it.
    if not str(chosen.get("send_cta") or "").strip():
        from reelbot.content.generator import default_send_cta

        chosen["send_cta"] = default_send_cta(chosen, format_key)

    log.info(
        "Using curated fallback lesson: %s (%d unused of %d in the %s pool)",
        chosen.get("title"), len(unused), len(pool), format_key,
    )
    return chosen
