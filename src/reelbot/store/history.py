"""What this account has already used, so it never repeats itself.

Three sources, because any one of them alone lies:

* ``lesson_history.json`` - titles this bot generated, published or not.
* the review queue - what is generated but still waiting for approval.
* ``published.json`` - what Instagram actually shows, which includes posts made
  by hand and posts made before this bot existed.

Matching is on a normalised *subject*, not the raw string. The account posted
``Stop Saying "Very Busy"`` and, four days later, ``Stop saying "Very Busy"!
Want to sound instantly more natural`` - two different strings, one lesson, and
the second one drew 170 views against the first one's 165.

History entries used to be bare title strings. They still may be: the reader
accepts both shapes so an existing ``lesson_history.json`` keeps working.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime

from reelbot.store.jsonstore import read_json, write_json
from reelbot.store.paths import HISTORY_FILE

log = logging.getLogger(__name__)

#: Keep this many past lessons. The prompt only ever cites the most recent 25.
MAX_ENTRIES = 400

#: Leading verbs that introduce the real subject rather than being it.
_LEAD = re.compile(
    r"^(?:so\s+)?(?:stop|quit|never|avoid|dont|do\s+not|please\s+stop)\s+"
    r"(?:say|saying|use|using|write|writing|confuse|confusing"
    r"|mix\s+up|mixing\s+up|sound|sounding)\s+",
    re.I,
)

#: A phrase in quotes is almost always the lesson's actual subject.
_QUOTED = re.compile("[\"'‘’“”]([^\"'‘’“”]{2,40})"
                     "[\"'‘’“”]")

#: Caption heads run on past the hook; only the first sentence identifies it.
_SENTENCE_END = re.compile(r"[.!?—\n]")

#: The topic is not always at the front. "Three Better Words Than Very Happy"
#: teaches the same lesson as "Stop Saying 'Very Happy'", but only the second
#: one opens with it. These pull the subject out of the middle of a title.
#: Deliberately narrow. A bare "say ___" rule was tried and matched "What to
#: Say When You Miss a Deadline" as the topic "when", colliding with every other
#: "What to Say When ..." lesson. An intensifier or "instead of" is specific
#: enough that the next word really is the subject.
_MID_TOPIC = (
    re.compile(r"\b(?:very|really|extremely|super)\s+(\w+(?:\s+\w+)?)"),
    re.compile(r"\binstead\s+of\s+(\w+(?:\s+\w+)?)"),
)

_NON_WORD = re.compile(r"[^a-z0-9\s]+")
_SPACES = re.compile(r"\s+")

#: Words that carry no topic, so two titles differing only in these collide.
_FILLER = frozenset(
    "a an the this that these those your you my his her their our its it is are"
    " was were be to in on of for and or but with without do does did dont"
    " if now new more most very really just so too can could should would"
    " from than when at by as into about after before".split()
)

#: How many significant words make a subject key. Long enough to separate two
#: real lessons, short enough that trailing hype does not hide a repeat.
_SUBJECT_WORDS = 4


def _strip(text: str) -> str:
    """Lowercase, drop emoji and punctuation, collapse whitespace."""
    lowered = str(text or "").lower()
    return _SPACES.sub(" ", _NON_WORD.sub(" ", lowered)).strip()


def normalise(text: str) -> str:
    """A comparable form of ``text``: no case, emoji, punctuation or filler."""
    words = [w for w in _strip(text).split() if w not in _FILLER]
    return " ".join(words)


def subject(text: str) -> str:
    """The topic ``text`` teaches, stripped of the hook wrapped around it.

    ``Stop Saying "Very Busy"``, ``❌ Stop Saying Very Busy 🤯`` and ``Never say
    very busy at work!`` reduce to ``busy``, ``busy`` and ``busy at work`` - see
    :func:`matches` for why the last one still counts as the same lesson.
    """
    raw = str(text or "").strip()
    if not raw:
        return ""

    quoted = _QUOTED.search(raw)
    if quoted:
        inner = normalise(quoted.group(1))
        if inner:
            return " ".join(inner.split()[:_SUBJECT_WORDS])

    # Punctuation and emoji are removed before the lead is matched, so a title
    # opening with "❌ Stop saying ..." is stripped like a plain one.
    head = _strip(_SENTENCE_END.split(raw, 1)[0])

    for pattern in _MID_TOPIC:
        found = pattern.search(head)
        if found:
            words = [w for w in found.group(1).split() if w not in _FILLER]
            if words:
                return " ".join(words[:_SUBJECT_WORDS])

    words = [w for w in _LEAD.sub("", head).split() if w not in _FILLER]
    return " ".join(words[:_SUBJECT_WORDS])


def matches(one: str, other: str) -> bool:
    """True if two subject keys name the same lesson.

    Compared as word prefixes rather than for equality. A subject is a truncated
    phrase, so the same lesson can surface as ``busy`` from one title and ``busy
    at work`` from another; requiring equality would let that pair through.
    """
    left, right = str(one or "").split(), str(other or "").split()
    if not left or not right:
        return False
    shared = min(len(left), len(right))
    return left[:shared] == right[:shared]


def matches_any(key: str, keys) -> bool:
    """True if ``key`` names the same lesson as anything in ``keys``."""
    return any(matches(key, other) for other in keys)


#: Per-format field holding the thing being taught, used as a content key.
_SUBJECT_FIELDS = ("basic", "wrong", "textbook", "word", "casual")


def lesson_keys(lesson: dict) -> list[str]:
    """Every string that identifies what ``lesson`` teaches.

    The title alone is not enough: quiz titles are interchangeable hype
    (``95% Fail This Quiz!``) while the question is the actual lesson.
    """
    keys: set[str] = set()
    for candidate in (subject(lesson.get("title")), normalise(lesson.get("question"))):
        if candidate:
            keys.add(candidate)

    for item in lesson.get("items") or []:
        if not isinstance(item, dict):
            continue
        for field in _SUBJECT_FIELDS:
            value = subject(item.get(field))
            if value:
                keys.add(value)
    return sorted(keys)


# --- Storage -------------------------------------------------------------

def load_entries() -> list[dict]:
    """Every remembered lesson, oldest first, normalised to dict form."""
    raw = read_json(HISTORY_FILE, [])
    if not isinstance(raw, list):
        return []

    entries: list[dict] = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            entries.append({"title": item.strip(), "keys": [subject(item)]})
        elif isinstance(item, dict) and str(item.get("title", "")).strip():
            keys = [str(k) for k in item.get("keys") or [] if str(k).strip()]
            entries.append({**item, "keys": keys or [subject(item["title"])]})
    return entries


def load_history() -> list[str]:
    """Every remembered lesson title, oldest first."""
    return [entry["title"] for entry in load_entries()]


def remember(title: str, lesson: dict | None = None) -> None:
    """Record a lesson as used, moving it to the end if already present."""
    cleaned = str(title or "").strip()
    if not cleaned:
        return

    keys = lesson_keys({**(lesson or {}), "title": cleaned})
    entry = {
        "title": cleaned,
        "format": str((lesson or {}).get("format") or ""),
        "keys": keys,
        "at": datetime.now().isoformat(timespec="seconds"),
    }
    kept = [e for e in load_entries() if e["title"] != cleaned]
    write_json(HISTORY_FILE, (kept + [entry])[-MAX_ENTRIES:])


def recent(limit: int = 25) -> list[str]:
    """The ``limit`` most recently used titles."""
    return load_history()[-limit:]


# --- What Instagram already shows ---------------------------------------

def _published_titles() -> list[str]:
    """Titles of posts that are live on the account.

    Prefers the queue title behind a post, because a caption head is the hook
    with marketing wrapped around it. Falls back to the caption for anything
    posted by hand or before this bot existed.
    """
    try:
        from reelbot.publish import queue, sync

        by_id = {item.id: item.title for item in queue.load()}
        titles = [by_id.get(post.queue_id) or post.caption_head for post in sync.load()]
        return [t for t in titles if str(t).strip()]
    except Exception as exc:  # noqa: BLE001 - a missing state file is not fatal
        log.debug("Could not read published titles: %s", exc)
        return []


def _queued_titles() -> list[str]:
    try:
        from reelbot.publish import queue

        return [item.title for item in queue.load() if str(item.title).strip()]
    except Exception as exc:  # noqa: BLE001
        log.debug("Could not read queued titles: %s", exc)
        return []


def used_titles() -> list[str]:
    """Every title the account has used, from all three sources, oldest first.

    This is what the generator is told to avoid. It is deliberately wider than
    :func:`load_history`: a topic posted by hand is still a topic the audience
    has already seen.
    """
    seen: set[str] = set()
    ordered: list[str] = []
    # Local history goes last, so its ordering - which drives the hook cooldown
    # window - stays the most recent thing the prompt sees.
    for title in _published_titles() + _queued_titles() + load_history():
        key = normalise(title)
        if key and key not in seen:
            seen.add(key)
            ordered.append(str(title).strip())
    return ordered


def used_keys() -> set[str]:
    """Every subject the account has already covered, from all three sources."""
    keys = {k for entry in load_entries() for k in entry["keys"]}
    keys |= {subject(t) for t in _published_titles() + _queued_titles()}
    return {k for k in keys if k}


def is_repeat(lesson: dict | str, used: set[str] | None = None) -> bool:
    """True if this lesson teaches something the account has already posted.

    A title-subject collision is enough on its own. A content collision has to
    be total: vocabulary lessons legitimately reuse a word or two, so rejecting
    on a single shared item would reject almost everything.
    """
    lesson = {"title": lesson} if isinstance(lesson, str) else dict(lesson or {})
    used = used_keys() if used is None else used
    if not used:
        return False

    title_key = subject(lesson.get("title"))
    if title_key and matches_any(title_key, used):
        return True

    content = [k for k in lesson_keys(lesson) if k != title_key]
    return bool(content) and all(matches_any(key, used) for key in content)
