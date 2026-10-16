"""Pixel-level guards that slides stay inside the drawable area.

Rendered against deliberately over-long copy, because that is what actually
breaks layouts: a model returns a 90-character example, a fixed font size
overflows its panel, and text ends up under Instagram's caption bar or off the
right edge of the canvas.

The checks work by rendering onto a flat canvas and asserting the forbidden
bands are still exactly the background colour.
"""
from __future__ import annotations

import pytest
from PIL import Image, ImageDraw

from reelbot.render.components import subtitle_top
from reelbot.render.slides import SLIDE_RENDERERS, render_slide
from reelbot.render.theme import CONTENT_RIGHT, HEIGHT, SAFE_TOP, WIDTH, reel_fonts

BACKGROUND = (0, 0, 0)

#: Copy far longer than the prompt allows, to prove the layout degrades safely.
LONG_PHRASE = "Very busy and completely overwhelmed beyond all reasonable measure"
LONG_SENTENCE = (
    "I am completely and utterly swamped with back-to-back emails and meetings "
    "today, honestly, and it never seems to stop."
)
LONG_MEANING = "To an extremely unusual degree, far beyond what is normal or expected here"


def _stress_item() -> dict:
    return {
        "basic": LONG_PHRASE, "advanced": "Absolutely swamped beyond belief",
        "textbook": LONG_PHRASE, "native": "Snowed under completely",
        "casual": LONG_PHRASE, "corporate": "I do not have the bandwidth right now",
        "word": "Extraordinarily", "type": "Adverb of manner", "meaning": LONG_MEANING,
        "nuance": LONG_MEANING, "context": LONG_MEANING, "situation": LONG_MEANING,
        "example": LONG_SENTENCE, "right": "Exceptional",
    }


def _stress_lesson() -> dict:
    item = _stress_item()
    return {
        "badge": "VOCABULARY BOOST",
        "title": "Stop Saying These Extremely Overused English Phrases Right Now Today",
        "subtitle": "Sound like a genuinely confident native speaker instead of a textbook",
        "rule": "A is for Action which means Affect, and E is for End result which means Effect",
        "question": (
            "Despite the fact that he had been working there for many years, "
            "he was still not accustomed _ the constant noise."
        ),
        "options": [
            "A) to the constant noise", "B) with the constant noise",
            "C) for the constant noise", "D) at the constant noise",
        ],
        "correct_option": "A",
        "correct_text": "A) to the constant noise",
        "explanation": (
            "The adjective 'accustomed' always pairs with the dependent "
            "preposition 'to', never with 'with', 'for' or 'at' in this context."
        ),
        "items": [item, item, item, item],
    }


def _scene(scene_type: str) -> dict:
    lesson = _stress_lesson()
    return {
        "type": scene_type,
        "data": _stress_item() if scene_type.endswith(("_item", "_word")) else lesson,
        "item_index": 0, "total_items": 3,
        "word_index": 0, "total_words": 2,
        "duration": 3.0,
    }


def _render(scene_type: str, scene_time: float) -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
    render_slide(ImageDraw.Draw(image), _scene(scene_type), scene_time, reel_fonts())
    return image


def _band_is_clean(image: Image.Image, box: tuple[int, int, int, int]) -> bool:
    region = image.crop(box)
    return region.getbbox() is None  # nothing but the (black) background


ALL_TYPES = sorted(SLIDE_RENDERERS)
TIMES = [0.5, 3.0, 8.0]


@pytest.mark.parametrize("scene_type", ALL_TYPES)
@pytest.mark.parametrize("scene_time", TIMES)
def test_nothing_is_drawn_under_the_caption_band(scene_type, scene_time):
    """Text here is covered by Instagram's caption and audio attribution."""
    image = _render(scene_type, scene_time)
    limit = subtitle_top(reel_fonts())
    assert _band_is_clean(image, (0, limit, WIDTH, HEIGHT)), (
        f"{scene_type} at t={scene_time}s draws below y={limit}, inside the caption band"
    )


@pytest.mark.parametrize("scene_type", ALL_TYPES)
def test_nothing_is_drawn_above_the_safe_top(scene_type):
    """The status bar and Reels controls sit here."""
    image = _render(scene_type, 8.0)
    assert _band_is_clean(image, (0, 0, WIDTH, SAFE_TOP)), (
        f"{scene_type} draws above y={SAFE_TOP}, under the status bar"
    )


@pytest.mark.parametrize("scene_type", ALL_TYPES)
def test_nothing_overflows_the_right_edge(scene_type):
    """Long options used to run straight off the canvas past the action column."""
    image = _render(scene_type, 8.0)
    assert _band_is_clean(image, (CONTENT_RIGHT + 2, 0, WIDTH, HEIGHT)), (
        f"{scene_type} draws past x={CONTENT_RIGHT}, into the action-button column"
    )


@pytest.mark.parametrize("scene_type", ALL_TYPES)
def test_slide_actually_renders_content(scene_type):
    """A slide that draws nothing would trivially pass the bounds checks."""
    image = _render(scene_type, 8.0)
    assert image.getbbox() is not None, f"{scene_type} rendered an empty frame"


# --- Cover / thumbnail ---------------------------------------------------

def _render_cover(lesson: dict, tmp_path) -> Image.Image:
    from reelbot.render.thumbnail import create_thumbnail

    out = create_thumbnail(lesson, tmp_path / "cover.jpg")
    assert out is not None, "cover generation returned nothing"
    return Image.open(out).convert("RGB")


def _rows_differ_from_edges(image: Image.Image, top: int, bottom: int) -> bool:
    """True if any row in [top, bottom) carries content beyond the flat gradient.

    The cover paints a full-frame gradient, so a band cannot be tested for
    'empty'. Instead each row is compared against its own left edge pixel:
    a row containing text or a pill will differ somewhere along its width.
    """
    pixels = image.load()
    for y in range(top, bottom, 3):
        edge = pixels[4, y]
        for x in range(8, image.width - 8, 3):
            if pixels[x, y] != edge:
                return True
    return False


@pytest.mark.parametrize("title", [
    "Stop Saying Very Busy",
    "Stop Saying These Extremely Overused English Phrases Right Now Today",
])
def test_cover_content_survives_the_profile_grid_crop(title, tmp_path):
    """The grid shows only the centre 1080x1350; anything outside is cut."""
    from reelbot.render.theme import COVER_BOTTOM, COVER_TOP

    lesson = dict(_stress_lesson(), title=title)
    image = _render_cover(lesson, tmp_path)

    assert not _rows_differ_from_edges(image, 0, COVER_TOP), (
        f"cover draws above y={COVER_TOP}; the profile grid crops it off"
    )
    assert not _rows_differ_from_edges(image, COVER_BOTTOM, HEIGHT), (
        f"cover draws below y={COVER_BOTTOM}; the profile grid crops it off"
    )


def test_cover_actually_has_content_in_the_crop(tmp_path):
    from reelbot.render.theme import COVER_BOTTOM, COVER_TOP

    image = _render_cover(_stress_lesson(), tmp_path)
    assert _rows_differ_from_edges(image, COVER_TOP, COVER_BOTTOM)


def test_quiz_cover_shows_the_question_not_a_title_card(tmp_path):
    """The account's top three quizzes all had question covers; its worst had
    a generic title card (1,188 / 530 / 223 views vs 56)."""
    from reelbot.content import fallbacks
    from reelbot.render.thumbnail import create_thumbnail

    lesson = fallbacks.pick("quiz")
    out = create_thumbnail(lesson, tmp_path / "quiz_cover.jpg")
    assert out is not None

    image = Image.open(out).convert("RGB")
    from reelbot.render.theme import COVER_BOTTOM, COVER_TOP

    # The question slide is much denser than a title card: assert the cover
    # carries content across most of the crop, not just a centred headline.
    rows_with_content = sum(
        1 for y in range(COVER_TOP, COVER_BOTTOM, 10)
        if _rows_differ_from_edges(image, y, y + 1)
    )
    total_rows = len(range(COVER_TOP, COVER_BOTTOM, 10))
    assert rows_with_content / total_rows > 0.5, (
        "quiz cover looks like a sparse title card, not the question frame"
    )


def test_quiz_cover_stays_inside_the_grid_crop(tmp_path):
    from reelbot.content import fallbacks
    from reelbot.render.theme import COVER_BOTTOM, COVER_TOP
    from reelbot.render.thumbnail import create_thumbnail

    out = create_thumbnail(fallbacks.pick("quiz"), tmp_path / "q.jpg")
    image = Image.open(out).convert("RGB")
    assert not _rows_differ_from_edges(image, 0, COVER_TOP)
    assert not _rows_differ_from_edges(image, COVER_BOTTOM, HEIGHT)


def test_non_quiz_still_uses_the_title_cover(tmp_path):
    from reelbot.content import fallbacks
    from reelbot.render.thumbnail import create_thumbnail

    out = create_thumbnail(fallbacks.pick("vocab"), tmp_path / "v.jpg")
    assert out is not None and out.exists()
