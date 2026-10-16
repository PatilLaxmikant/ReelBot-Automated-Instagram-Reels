"""Text must stay inside the panel it belongs to.

The pixel tests in ``test_layout_overflow`` prove nothing is drawn in a
forbidden *band* of the frame. They cannot see a heading spilling out of its own
rounded box in the middle of the slide - which is how the recap rows shipped
looking broken while the whole suite stayed green.

These tests record panel and text geometry as it is drawn (see
``reelbot.render.probe``) and assert containment directly.
"""
from __future__ import annotations

import pytest
from PIL import Image, ImageDraw

from reelbot.render import probe
from reelbot.render.slides import SLIDE_RENDERERS, render_slide
from reelbot.render.theme import HEIGHT, WIDTH, reel_fonts

from tests.test_layout_overflow import _scene  # deliberately over-long copy

#: Panels are drawn with a border a few px wide, and text is optically centred
#: against ink bounds, so a small overhang is not a real defect.
TOLERANCE = 5.0

ALL_TYPES = sorted(SLIDE_RENDERERS)
#: Sample across the reveal animation - elements move as they arrive.
TIMES = [0.6, 1.6, 3.0, 8.0]

#: Both extremes matter, and for opposite reasons. Long copy overflows a fixed
#: font. SHORT copy is what lets the auto-fit pick the largest face in the
#: ladder, which is how the recap rows overflowed their boxes originally - a
#: long-copy-only suite misses that entirely.
SHORT = {
    "basic": "Very busy", "advanced": "Swamped",
    "textbook": "I will think", "native": "Sleep on it",
    "casual": "I don't know", "corporate": "Let me check",
    "word": "Affect", "type": "Verb", "meaning": "To influence",
    "nuance": "Too much work", "context": "Deciding", "situation": "Buying time",
    "example": "I'm swamped.", "right": "Excellent", "wrong": "Very good",
}


def _short_scene(scene_type: str) -> dict:
    lesson = {
        "badge": "VOCABULARY", "title": "Stop Saying Very Busy",
        "subtitle": "Say this instead", "rule": "A is Action",
        "question": "I live here _ 3 years.",
        "options": ["A) since", "B) for", "C) from", "D) during"],
        "correct_option": "B", "correct_text": "B) for",
        "explanation": "Use FOR with durations.",
        "send_cta": "Send this to a friend",
        "items": [dict(SHORT) for _ in range(4)],
    }
    return {
        "type": scene_type,
        "data": dict(SHORT) if scene_type.endswith(("_item", "_word")) else lesson,
        "item_index": 0, "total_items": 3,
        "word_index": 0, "total_words": 2,
        "duration": 3.0,
    }


CONTENT = {"long": _scene, "short": _short_scene}


def _record(scene_type: str, scene_time: float, build=_scene) -> probe.Recorder:
    canvas = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
    with probe.recording() as recorder:
        render_slide(ImageDraw.Draw(canvas), build(scene_type), scene_time, reel_fonts())
    return recorder


def _describe(escaped) -> str:
    return "; ".join(
        f"{content[:32]!r} at {[round(v) for v in box]} escapes {[round(v) for v in panel]}"
        for content, box, panel in escaped
    )


@pytest.mark.parametrize("scene_type", ALL_TYPES)
@pytest.mark.parametrize("scene_time", TIMES)
@pytest.mark.parametrize("length", sorted(CONTENT))
def test_text_stays_inside_its_panel(scene_type, scene_time, length):
    recorder = _record(scene_type, scene_time, CONTENT[length])
    escaped = recorder.overflows(TOLERANCE)
    assert not escaped, (
        f"{scene_type} at t={scene_time}s with {length} copy: {_describe(escaped)}"
    )


@pytest.mark.parametrize("scene_type", ALL_TYPES)
def test_panels_are_recorded_at_all(scene_type):
    """Guards the guard: containment passes trivially if nothing is recorded."""
    recorder = _record(scene_type, 8.0)
    assert recorder.panels, f"{scene_type} drew no panels - the probe is not wired in"
    assert recorder.texts, f"{scene_type} drew no text - the probe is not wired in"


@pytest.mark.parametrize("scene_type", ALL_TYPES)
@pytest.mark.parametrize("length", sorted(CONTENT))
def test_panels_do_not_overlap_each_other(scene_type, length):
    """Sibling panels must not collide; nesting is allowed."""
    panels = _record(scene_type, 8.0, CONTENT[length]).panels
    for index, first in enumerate(panels):
        for second in panels[index + 1:]:
            overlap_w = min(first[2], second[2]) - max(first[0], second[0])
            overlap_h = min(first[3], second[3]) - max(first[1], second[1])
            if overlap_w <= TOLERANCE or overlap_h <= TOLERANCE:
                continue  # disjoint, or touching borders
            contained = (
                first[0] >= second[0] - TOLERANCE and first[1] >= second[1] - TOLERANCE
                and first[2] <= second[2] + TOLERANCE and first[3] <= second[3] + TOLERANCE
            ) or (
                second[0] >= first[0] - TOLERANCE and second[1] >= first[1] - TOLERANCE
                and second[2] <= first[2] + TOLERANCE and second[3] <= first[3] + TOLERANCE
            )
            assert contained, (
                f"{scene_type}: panels {[round(v) for v in first]} and "
                f"{[round(v) for v in second]} overlap without nesting"
            )


class TestProbeItself:
    """The detector has to be able to fail, or it proves nothing."""

    def test_detects_a_planted_overflow(self):
        from reelbot.render.fonts import ROBOTO_BOLD, load
        from reelbot.render.text import draw_text

        canvas = Image.new("RGB", (400, 200), (0, 0, 0))
        draw = ImageDraw.Draw(canvas)
        with probe.recording() as recorder:
            probe.note_panel((10, 10, 200, 60))
            draw_text(draw, (20, 20), "far too long for this box", load(ROBOTO_BOLD, 46), (255, 255, 255))
        assert recorder.overflows(TOLERANCE), "the probe missed an obvious overflow"

    def test_ignores_text_that_fits(self):
        from reelbot.render.fonts import ROBOTO_BOLD, load
        from reelbot.render.text import draw_text

        canvas = Image.new("RGB", (400, 200), (0, 0, 0))
        draw = ImageDraw.Draw(canvas)
        with probe.recording() as recorder:
            probe.note_panel((10, 10, 380, 120))
            draw_text(draw, (20, 20), "Fits", load(ROBOTO_BOLD, 46), (255, 255, 255))
        assert not recorder.overflows(TOLERANCE)

    def test_free_floating_text_has_no_owner(self):
        """A slide title on bare background is not inside any panel."""
        recorder = probe.Recorder()
        recorder.panels.append((0, 0, 100, 100))
        assert recorder.owner_of((500, 500, 600, 540)) is None

    def test_smallest_containing_panel_wins(self):
        """Nested panels: the inner one owns the text."""
        recorder = probe.Recorder()
        recorder.panels.extend([(0, 0, 1000, 1000), (100, 100, 300, 300)])
        assert recorder.owner_of((110, 110, 200, 140)) == (100, 100, 300, 300)

    def test_recording_is_inert_when_inactive(self):
        probe.note_panel((0, 0, 10, 10))
        probe.note_text((0, 0, 10, 10), "x")
        assert not probe.is_recording()
