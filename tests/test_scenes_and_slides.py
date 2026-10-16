"""Scene building and the scene-type -> renderer contract.

The regression guarded here: the scene builder emitted ``mistake_trick`` while
the renderer only handled ``mistake_rule``, so the memory-trick slide rendered
as an empty gradient in every published `mistake` reel.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from reelbot.audio.scenes import build_lesson_scenes, clean_script
from reelbot.formats import NARRATED_FORMATS
from reelbot.render.slides import SLIDE_RENDERERS, render_slide
from reelbot.render.theme import HEIGHT, WIDTH, reel_fonts

_LESSONS = json.loads(
    (Path(__file__).parents[1] / "src/reelbot/content/fallback_lessons.json").read_text("utf-8")
)


def lesson_for(format_key: str) -> dict:
    lesson = dict(_LESSONS[format_key][0])
    lesson["format"] = format_key
    return lesson


@pytest.mark.parametrize("format_key", NARRATED_FORMATS)
def test_every_emitted_scene_type_has_a_renderer(format_key):
    """No scene may fall through to the default and render a blank slide."""
    scenes = build_lesson_scenes(lesson_for(format_key))
    assert scenes, f"{format_key} produced no scenes"
    for scene in scenes:
        assert scene["type"] in SLIDE_RENDERERS, (
            f"{format_key} emits scene type {scene['type']!r} with no registered renderer"
        )


@pytest.mark.parametrize("format_key", NARRATED_FORMATS)
def test_every_scene_has_narration_text(format_key):
    for scene in build_lesson_scenes(lesson_for(format_key)):
        assert scene["text"].strip(), f"{format_key}/{scene['id']} has empty narration"


def test_mistake_format_emits_the_trick_scene():
    types = [s["type"] for s in build_lesson_scenes(lesson_for("mistake"))]
    assert "mistake_trick" in types
    assert types[-1] == "mistake_trick", "the memory trick must be the payoff scene"


def test_card_format_produces_no_scenes():
    """Cards are music-only, so they must not enter the narration path."""
    assert build_lesson_scenes(lesson_for("card")) == []


def test_quiz_scene_order():
    types = [s["type"] for s in build_lesson_scenes(lesson_for("quiz"))]
    assert types == ["quiz_question", "quiz_countdown", "quiz_reveal"]


class TestCleanScript:
    def test_blank_becomes_spoken_word(self):
        assert "blank" in clean_script("conducive _ productivity")

    def test_markdown_is_stripped(self):
        assert clean_script("**bold** text") == "bold text"

    def test_whitespace_collapsed(self):
        assert clean_script("too   many    spaces") == "too many spaces"


@pytest.mark.parametrize("scene_type", sorted(SLIDE_RENDERERS))
def test_every_renderer_draws_something(scene_type):
    """Each renderer must put pixels on the canvas, not leave it blank."""
    fonts = reel_fonts()
    format_key = scene_type.split("_")[0]
    lesson = lesson_for(format_key)

    scene = next(
        (s for s in build_lesson_scenes(lesson) if s["type"] == scene_type),
        {"type": scene_type, "data": lesson, "duration": 3.0},
    )

    blank = Image.new("RGB", (WIDTH, HEIGHT), (11, 15, 25))
    canvas = blank.copy()
    render_slide(ImageDraw.Draw(canvas), scene, 1.0, fonts)

    assert canvas.tobytes() != blank.tobytes(), f"{scene_type} rendered an empty frame"
