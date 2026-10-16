"""Gemini-backed lesson generation with schema validation.

A malformed model response used to flow straight into the renderer and produce
a broken reel. Responses are now validated against the shape each format needs;
anything that fails validation falls back to a curated lesson.
"""
from __future__ import annotations

import json
import logging
import random

from reelbot.content import fallbacks, hooks
from reelbot.formats import (
    ALL_FORMATS,
    FORMAT_CARD,
    FORMAT_CORPORATE,
    FORMAT_MISTAKE,
    FORMAT_NATIVE,
    FORMAT_QUIZ,
    FORMAT_VOCAB,
    get_spec,
)
from reelbot.render.text import clean_blank
from reelbot.settings import get_settings
from reelbot.store import history as history_store

log = logging.getLogger(__name__)

#: Required keys on each item, per format, plus the minimum item count.
_ITEM_SCHEMA: dict[str, tuple[tuple[str, ...], int]] = {
    FORMAT_VOCAB: (("basic", "advanced", "example"), 2),
    FORMAT_NATIVE: (("textbook", "native", "example"), 2),
    FORMAT_MISTAKE: (("word", "meaning", "example"), 2),
    FORMAT_CORPORATE: (("casual", "corporate", "example"), 3),
    # Card examples are caption-only (the image has no room), but they are the
    # format's teaching value, so a response without them is not usable.
    FORMAT_CARD: (("wrong", "right", "example"), 3),
}


class ValidationError(ValueError):
    """Raised when a generated lesson does not match its format's schema."""


def validate_lesson(lesson: dict, format_key: str) -> None:
    """Raise :class:`ValidationError` if ``lesson`` is unusable for ``format_key``."""
    if not isinstance(lesson, dict):
        raise ValidationError("Response was not a JSON object")
    if not str(lesson.get("title", "")).strip():
        raise ValidationError("Missing 'title'")

    if format_key == FORMAT_QUIZ:
        if not str(lesson.get("question", "")).strip():
            raise ValidationError("Quiz is missing 'question'")
        options = lesson.get("options")
        if not isinstance(options, list) or len(options) < 2:
            raise ValidationError("Quiz needs at least 2 'options'")
        if not str(lesson.get("correct_option", "")).strip():
            raise ValidationError("Quiz is missing 'correct_option'")
        if not str(lesson.get("explanation", "")).strip():
            raise ValidationError("Quiz is missing 'explanation'")
        return

    required, minimum = _ITEM_SCHEMA[format_key]
    items = lesson.get("items")
    if not isinstance(items, list) or len(items) < minimum:
        raise ValidationError(f"{format_key} needs at least {minimum} items, got {len(items or [])}")

    for position, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValidationError(f"Item {position} is not an object")
        missing = [key for key in required if not str(item.get(key, "")).strip()]
        if missing:
            raise ValidationError(f"Item {position} is missing {', '.join(missing)}")


#: Fallback send prompts, used when the model omits `send_cta`.
#: Each names a specific person rather than saying "share this" - DM sends are
#: the heaviest-weighted reel signal, and only specificity triggers them.
_SEND_CTA_DEFAULTS = {
    FORMAT_VOCAB: "Send this to someone who always says '{basic}'",
    FORMAT_NATIVE: "Send this to a friend who still talks like a textbook",
    FORMAT_QUIZ: "Send this to someone who thinks their English is perfect",
    FORMAT_MISTAKE: "Send this to someone who still mixes these two up",
    FORMAT_CORPORATE: "Send this to the colleague who writes blunt emails",
    FORMAT_CARD: "Send this to a friend who is learning English",
}


def default_send_cta(lesson: dict, format_key: str) -> str:
    """A specific, person-naming send prompt derived from the lesson."""
    template = _SEND_CTA_DEFAULTS.get(format_key, _SEND_CTA_DEFAULTS[FORMAT_VOCAB])
    items = lesson.get("items") or [{}]
    basic = str(items[0].get("basic") or items[0].get("wrong") or "that").strip()
    return template.format(basic=basic)


def _normalise(lesson: dict, format_key: str) -> dict:
    """Apply the cleanups every downstream stage assumes have happened."""
    lesson["format"] = format_key
    lesson.setdefault("badge", get_spec(format_key).badge)

    send_cta = str(lesson.get("send_cta") or "").strip()
    lesson["send_cta"] = send_cta or default_send_cta(lesson, format_key)

    if lesson.get("question"):
        lesson["question"] = clean_blank(lesson["question"])

    # The generator is told not to emit hashtags; hashtags.py owns them.
    caption = lesson.get("caption") or lesson.get("instagram_caption") or ""
    lesson["caption"] = str(caption).strip()
    lesson.pop("instagram_caption", None)
    return lesson


def generate_lesson(format_key: str | None = None, history: list[str] | None = None) -> dict:
    """Generate one lesson, falling back to curated content on any failure.

    Args:
        history: titles the account has already used. Omit it to load the full
            account memory - local history, the queue, and what is live on
            Instagram. Pass a list (including an empty one) to supply the memory
            explicitly; nothing else is consulted, which is what makes this
            testable without touching the project's state files.
    """
    if not format_key or format_key not in ALL_FORMATS:
        format_key = random.choice(ALL_FORMATS)

    if history is None:
        titles, used = history_store.used_titles(), history_store.used_keys()
    else:
        titles = list(history)
        used = {history_store.subject(title) for title in titles} - {""}

    settings = get_settings()
    if not settings.has_gemini:
        log.info("No GEMINI_API_KEY set - using a curated fallback lesson.")
        return fallbacks.pick(format_key, titles)

    try:
        # Imported lazily so the package works without google-genai installed.
        from google import genai

        from reelbot.content.prompts import build_prompt

        log.info("Generating %s lesson with %s ...", format_key.upper(), settings.gemini_model)
        client = genai.Client(api_key=settings.gemini_api_key)
        hook_ban = hooks.avoid_clause(titles)

        def ask(insist: bool) -> dict:
            response = client.models.generate_content(
                model=settings.gemini_model,
                contents=build_prompt(
                    format_key, titles[-25:], hook_ban=hook_ban, insist=insist,
                    banned_subjects=sorted(used)[:120],
                ),
                config={"response_mime_type": "application/json"},
            )
            candidate = json.loads(response.text)
            validate_lesson(candidate, format_key)
            return candidate

        #: How bad a repeat is. A repeated *topic* means the audience has
        #: already been taught this lesson and is unacceptable; a repeated
        #: *hook shape* only means the title looks familiar, which is tolerable
        #: on genuinely new content.
        FRESH, HOOK, TOPIC = 0, 1, 2

        def staleness(candidate: dict) -> int:
            if history_store.is_repeat({**candidate, "format": format_key}, used):
                return TOPIC
            if hook_ban and hooks.is_on_cooldown(candidate.get("title", ""), titles):
                return HOOK
            return FRESH

        def why(candidate: dict, rank: int) -> str:
            title = candidate.get("title", "")
            if rank == TOPIC:
                return f"topic {title!r} is already covered"
            return f"hook pattern {hooks.describe(hooks.hook_family(title))!r} is on cooldown"

        lesson = ask(insist=False)

        # One retry, covering both problems. A second and third call for the
        # same post is API quota spent on diminishing returns.
        rank = staleness(lesson)
        if rank != FRESH:
            log.info("Regenerating - %s.", why(lesson, rank))
            try:
                retry = ask(insist=True)
                # Keep whichever is less stale; a tie keeps the first response.
                if staleness(retry) < rank:
                    lesson, rank = retry, staleness(retry)
                else:
                    log.warning("Retry did not improve on the first response.")
            except Exception as exc:  # noqa: BLE001
                log.warning("Retry failed (%s); keeping the first lesson.", exc)

        if rank == TOPIC:
            # The curated pool is guaranteed unused until it is exhausted, so a
            # fallback here is genuinely fresher than what the model produced.
            log.warning("Could not get an uncovered topic from the model; using a fallback.")
            return fallbacks.pick(format_key, titles)

        lesson = _normalise(lesson, format_key)
        log.info(
            "Generated lesson: %s  [hook: %s]",
            lesson.get("title"), hooks.hook_family(lesson.get("title", "")),
        )
        return lesson

    except ValidationError as exc:
        log.warning("Gemini returned an unusable lesson (%s); using fallback.", exc)
    except Exception as exc:  # noqa: BLE001 - network/SDK/JSON failures all fall back
        log.warning("Gemini generation failed (%s); using fallback.", exc)

    return fallbacks.pick(format_key, history)
