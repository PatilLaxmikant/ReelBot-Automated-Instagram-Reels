"""Rotating hashtag sets.

Posting the identical hashtag block every day is the single easiest pattern for
Instagram to fingerprint as automation, and it caps reach at one fixed audience
slice. This module builds a fresh mix per post from curated pools, preferring
the least-recently-used tags so the sets drift over time.

On count: Mosseri's position is that hashtags "have never been a good way to
actually increase your reach" - they categorise a post rather than distribute
it. That argues against a wall of forty tags, not for a handful. A set of five
gave the classifier almost nothing to work with and left the post out of every
niche feed it could plausibly have ranked in, so the target is now fifteen:
wide enough to be categorised precisely, small enough to stay on-topic.

The pools are curated, not scraped - nothing here reads live trend data.
"""
from __future__ import annotations

import logging
import random
import re
from collections import Counter

from reelbot.formats import get_spec
from reelbot.store.jsonstore import read_json, write_json
from reelbot.store.paths import HASHTAG_FILE

log = logging.getLogger(__name__)

#: Always present - these define the account's topic to the algorithm.
CORE = ("learnenglish", "englishtips")

#: High-volume tags: reach, but heavy competition.
BROAD = (
    "english", "englishlearning", "dailyenglish", "englishspeaking",
    "englishlesson", "esl", "englishteacher", "studyenglish",
    "englishgrammar", "learningenglish", "englishclass", "ingles",
    "speakenglish", "englishonline", "englishstudent", "efl",
    "englishcourse", "aprenderingles", "englishlanguage", "ielts",
)

#: Lower-volume tags: a small account ranks in these far more easily. This is
#: where a channel this size actually gets found, so the pool is the deepest.
NICHE = (
    "englishwithme", "englishpractice", "fluentenglish", "englishcoach",
    "spokenenglish", "englishvocab", "improveenglish", "englishskills",
    "englisheveryday", "confidentenglish", "englishforwork", "englishfluency",
    "practiceenglish", "englishhacks", "englishmadeeasy", "englishlearners",
    "learnenglishonline", "englishtipsdaily", "speakfluently", "englishspeakingpractice",
    "englishforbeginners", "advancedenglish", "englishpronunciation", "vocabularybuilding",
    "englishreels", "dailyvocabulary", "englishwords", "englishlearningtips",
)

#: Broad tags reach further; niche tags are where a small account ranks. The
#: split leans niche on purpose.
BROAD_PER_POST = 4
NICHE_PER_POST = 6
TOPIC_PER_POST = 3
TAG_TARGET = 15

#: How many of the least-used tags to draw each pick from. Taking strictly the
#: rarest would make consecutive posts share a predictable block; sampling from
#: a slightly wider band keeps the sets genuinely different.
_SHUFFLE_BAND = 2

_HASHTAG_RE = re.compile(r"(?:^|\s)#\w+")


def _usage() -> Counter:
    raw = read_json(HASHTAG_FILE, {})
    counts = raw.get("usage", raw) if isinstance(raw, dict) else {}
    return Counter({str(k): int(v) for k, v in counts.items() if isinstance(v, (int, float))})


def _save_usage(counts: Counter) -> None:
    write_json(HASHTAG_FILE, {"usage": dict(counts)})


def _least_used(pool: tuple[str, ...], counts: Counter, quantity: int) -> list[str]:
    """Pick ``quantity`` tags from ``pool``, favouring the least used."""
    if quantity <= 0 or not pool:
        return []
    ordered = sorted(pool, key=lambda tag: (counts.get(tag, 0), tag))
    band = ordered[: min(len(ordered), quantity * _SHUFFLE_BAND)]
    return random.sample(band, min(quantity, len(band)))


def build_hashtags(format_key: str, record: bool = True, target: int = TAG_TARGET) -> list[str]:
    """Compose the hashtag set for one post.

    Returns at most ``target`` tags: the account's core topic tags, then a mix
    drawn from the broad, niche and format-specific pools.

    Args:
        format_key: which content format the post uses.
        record: when True, persist the usage counts so the next call rotates.
        target: hard cap on the number of tags returned.
    """
    counts = _usage()
    topic_pool = get_spec(format_key).topic_tags

    tags = list(CORE)
    tags += _least_used(topic_pool, counts, TOPIC_PER_POST)
    tags += _least_used(NICHE, counts, NICHE_PER_POST)
    tags += _least_used(BROAD, counts, BROAD_PER_POST)

    # Preserve order while removing any overlap between pools, then cap.
    unique = list(dict.fromkeys(tags))[:target]

    # A pool overlap can leave the set short of target; top it up from the
    # niche pool, which is the one deep enough to spare tags.
    if len(unique) < target:
        for tag in sorted(NICHE, key=lambda t: (counts.get(t, 0), t)):
            if len(unique) >= target:
                break
            if tag not in unique:
                unique.append(tag)

    if record:
        counts.update(unique)
        _save_usage(counts)

    return unique


def strip_hashtags(caption: str) -> str:
    """Remove any hashtags the model wrote, so ours are the only ones."""
    if not caption:
        return ""
    without = _HASHTAG_RE.sub("", str(caption))
    return re.sub(r"\n{3,}", "\n\n", without).strip()


def apply_hashtags(caption: str, format_key: str, record: bool = True) -> str:
    """Return ``caption`` with a freshly rotated hashtag block appended."""
    body = strip_hashtags(caption)
    block = " ".join(f"#{tag}" for tag in build_hashtags(format_key, record=record))
    return f"{body}\n\n{block}".strip()
