"""Turn a lesson dict into the ordered list of scenes that drive the reel.

A "scene" pairs one narration script with one visual slide. Because narration
is synthesised per scene, the audio and the visuals share a single timeline and
cannot drift apart.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from reelbot.formats import (
    FORMAT_CORPORATE,
    FORMAT_MISTAKE,
    FORMAT_NATIVE,
    FORMAT_QUIZ,
    FORMAT_VOCAB,
)


def clean_script(text: str) -> str:
    """Normalise a script for speech: blanks become the spoken word 'blank'."""
    if not text:
        return ""
    cleaned = re.sub(r"_{1,}", " blank ", str(text))
    cleaned = cleaned.replace("**", "").replace("*", "")
    return re.sub(r"\s+", " ", cleaned).strip()


@dataclass(frozen=True)
class _ItemSpec:
    """How one format turns a single lesson item into a narrated scene."""

    scene_type: str
    index_key: str
    total_key: str
    narrate: Callable[[int, dict], str]


@dataclass(frozen=True)
class _FormatSpec:
    intro_type: str
    intro_default: str
    outro_type: str
    outro_default: str
    item: _ItemSpec


def _vocab_narration(idx: int, item: dict) -> str:
    return (
        f"Number {idx + 1}: {item.get('advanced', '')}. "
        f"{item.get('nuance', '')}. "
        f"For example: {item.get('example', '')}"
    )


def _native_narration(idx: int, item: dict) -> str:
    return (
        f"Instead of saying {item.get('textbook', '')}, "
        f"native speakers say: {item.get('native', '')}! "
        f"Example: {item.get('example', '')}"
    )


def _mistake_narration(idx: int, item: dict) -> str:
    return (
        f"{item.get('word', '')}. {item.get('meaning', '')}. "
        f"For example: {item.get('example', '')}"
    )


def _corporate_narration(idx: int, item: dict) -> str:
    return (
        f"Number {idx + 1}: Instead of saying {item.get('casual', '')}, "
        f"say: {item.get('corporate', '')}! "
        f"Example: {item.get('example', '')}"
    )


_SPECS: dict[str, _FormatSpec] = {
    FORMAT_VOCAB: _FormatSpec(
        intro_type="vocab_intro",
        intro_default="Stop saying it the basic way! Here are natural alternatives to sound fluent.",
        outro_type="vocab_outro",
        outro_default=(
            "Which phrase was your favorite? Save this reel for practice "
            "and comment your sentence below!"
        ),
        item=_ItemSpec("vocab_item", "item_index", "total_items", _vocab_narration),
    ),
    FORMAT_NATIVE: _FormatSpec(
        intro_type="native_intro",
        intro_default=(
            "What schools teach you versus what native speakers actually say! "
            "Stop sounding like a robot."
        ),
        outro_type="native_outro",
        outro_default=(
            "Which native phrase did you like most? Save this reel and write "
            "your sentence in the comments!"
        ),
        item=_ItemSpec("native_item", "item_index", "total_items", _native_narration),
    ),
    FORMAT_MISTAKE: _FormatSpec(
        intro_type="mistake_intro",
        intro_default="Stop confusing these two words! Here is the easiest memory trick.",
        outro_type="mistake_trick",
        outro_default="Remember this memory trick. Save this reel so you never forget!",
        item=_ItemSpec("mistake_word", "word_index", "total_words", _mistake_narration),
    ),
    FORMAT_CORPORATE: _FormatSpec(
        intro_type="corporate_intro",
        intro_default=(
            "POV: You want to sound professional at work! Here are four "
            "high-value phrases for your next meeting or email."
        ),
        outro_type="corporate_outro",
        outro_default=(
            "Which corporate phrase was your favorite? Save this cheat sheet "
            "for your next email and comment below!"
        ),
        item=_ItemSpec("corporate_item", "item_index", "total_items", _corporate_narration),
    ),
}


def _quiz_scenes(lesson: dict) -> list[dict]:
    spoken_question = clean_script(lesson.get("question", ""))
    intro = lesson.get("intro_script") or (
        f"Can you solve this in three seconds? Fill in the blank: {spoken_question}."
    )
    reveal = lesson.get("reveal_script") or (
        f"The correct answer is {lesson.get('correct_text', lesson.get('correct_option', ''))}! "
        f"{lesson.get('explanation', '')} Did you get it right? Comment below!"
    )
    return [
        {"id": "question", "type": "quiz_question", "text": clean_script(intro), "data": lesson},
        {
            "id": "countdown",
            "type": "quiz_countdown",
            "text": clean_script(lesson.get("countdown_script") or "Three, two, one..."),
            "data": lesson,
        },
        {"id": "reveal", "type": "quiz_reveal", "text": clean_script(reveal), "data": lesson},
    ]


#: Words per second measured on real edge-tts output (23 words / 8.2s on a
#: corporate reel). A ten-word hook therefore lands the first teaching item
#: inside four seconds instead of eight.
WORDS_PER_SECOND = 2.8
INTRO_MAX_WORDS = 10

_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+")

#: Words that must not end a truncated hook - they leave it hanging mid-clause.
_TRAILING_STOPWORDS = frozenset(
    "a an the and or but so of to in on at for with is are was were be been"
    " it its this that these those you your my our their he she they we".split()
)


def hook_script(text: str, max_words: int = INTRO_MAX_WORDS) -> str:
    """The shortest opening line that still reads as a whole sentence.

    Intro narration sets the length of the opening slide, because every scene
    lasts exactly as long as its own audio. A 23-word intro held a title card
    for 8.2 seconds before the reel taught anything - longer than most people
    watch. Only the first sentence is kept, and it is cut at ``max_words`` if
    even that runs long.
    """
    cleaned = clean_script(text)
    if not cleaned:
        return ""

    first = _SENTENCE_BREAK.split(cleaned, 1)[0].strip()
    words = first.split()
    if len(words) <= max_words:
        return first

    kept = words[:max_words]
    # Cutting at exactly ``max_words`` can land mid-clause - "one of the!" -
    # so back off over any trailing function words first.
    while len(kept) > 3 and kept[-1].strip(",;:").lower() in _TRAILING_STOPWORDS:
        kept.pop()

    trimmed = " ".join(kept).rstrip(",;:-")
    return trimmed if trimmed.endswith((".", "!", "?")) else trimmed + "."


def intro_scene_type(format_key: str) -> str:
    """The slide type a format opens on, or ``""`` if it has no narrated intro."""
    spec = _SPECS.get(format_key)
    return spec.intro_type if spec else ""


def build_lesson_scenes(lesson: dict) -> list[dict]:
    """Deconstruct ``lesson`` into ordered, narrated scenes.

    Card lessons are music-only and produce no scenes.
    """
    format_key = lesson.get("format", FORMAT_VOCAB)

    if format_key == FORMAT_QUIZ:
        return _quiz_scenes(lesson)

    spec = _SPECS.get(format_key)
    if spec is None:
        return []

    items = lesson.get("items", []) or []
    scenes: list[dict] = [
        {
            "id": "intro",
            "type": spec.intro_type,
            # Shortened on purpose: the opening slide lasts as long as this line.
            "text": hook_script(lesson.get("intro_script") or spec.intro_default),
            "data": lesson,
        }
    ]

    for idx, item in enumerate(items):
        narration = item.get("narration") or spec.item.narrate(idx, item)
        scenes.append(
            {
                "id": f"item_{idx}",
                "type": spec.item.scene_type,
                spec.item.index_key: idx,
                spec.item.total_key: len(items),
                "text": clean_script(narration),
                "data": item,
            }
        )

    outro_text = lesson.get("outro_script") or spec.outro_default
    if format_key == FORMAT_MISTAKE and lesson.get("rule"):
        outro_text = lesson.get("outro_script") or (
            f"Remember this easy memory trick: {lesson['rule']}. "
            "Save this reel so you never forget!"
        )

    scenes.append(
        {
            "id": "outro",
            "type": spec.outro_type,
            "text": clean_script(outro_text),
            "data": lesson,
        }
    )
    return scenes
