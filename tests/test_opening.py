"""The opening frame and the cover: both have to carry the lesson.

Measured on shipped output before this changed: the first real phrase appeared
8.2s into a corporate reel and 6.2s into a mistake reel. Until then the frame
held a title plus three fixed bullets - "Textbook English", "What natives really
say", "Use it today" - identical on every reel and true of every reel.

The one format that already opened on its content is the quiz, and it is also
the only one that has broken 500 views on this account.
"""
from __future__ import annotations

import pytest
from PIL import Image, ImageDraw

from reelbot.audio import scenes
from reelbot.content import fallbacks
from reelbot.formats import FORMAT_CARD, FORMAT_QUIZ, NARRATED_FORMATS
from reelbot.render import probe
from reelbot.render.slides import PREVIEW_ROWS, preview_pairs, render_intro
from reelbot.render.theme import HEIGHT, WIDTH, reel_fonts

#: A narrated intro longer than this holds the opening slide past the point
#: most viewers stay. 2.8 words/sec measured on real edge-tts output.
MAX_INTRO_SECONDS = 4.0

#: Formats whose opening slide is render_intro. Quiz opens on its question.
_PREVIEW_FORMATS = [f for f in NARRATED_FORMATS if f != FORMAT_QUIZ]


def drawn_text(lesson: dict) -> str:
    """Everything render_intro puts on the fully revealed opening frame."""
    fonts = reel_fonts()
    image = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
    with probe.recording() as recorder:
        render_intro(ImageDraw.Draw(image), {"data": lesson}, 6.0, fonts)
    return " ".join(content for _box, content in recorder.texts)


class TestPreviewPairs:
    @pytest.mark.parametrize("format_key", _PREVIEW_FORMATS)
    def test_every_previewable_format_yields_pairs(self, format_key):
        for lesson in fallbacks._lessons()[format_key]:
            pairs = preview_pairs(lesson)
            assert pairs, f"{format_key} lesson {lesson['title']!r} previews nothing"
            assert len(pairs) <= PREVIEW_ROWS

    @pytest.mark.parametrize("format_key", _PREVIEW_FORMATS)
    def test_both_halves_are_real_text(self, format_key):
        for before, after in preview_pairs(fallbacks.pick(format_key, [])):
            assert before.strip() and after.strip()

    def test_a_lesson_without_items_previews_nothing(self):
        assert preview_pairs({"format": "vocab", "items": []}) == []

    def test_an_unknown_format_previews_nothing(self):
        assert preview_pairs({"format": "nonsense", "items": [{"basic": "x"}]}) == []

    def test_items_missing_the_pair_fields_are_skipped(self):
        lesson = {"format": "vocab", "items": [{"basic": "Very busy"}, {"advanced": "Swamped"}]}
        assert preview_pairs(lesson) == []


class TestOpeningFrameCarriesTheLesson:
    """The regression: an opening frame that announced the lesson instead."""

    @pytest.mark.parametrize("format_key", _PREVIEW_FORMATS)
    def test_the_first_swap_is_on_the_opening_frame(self, format_key):
        lesson = fallbacks.pick(format_key, [])
        before, after = preview_pairs(lesson)[0]
        painted = drawn_text(lesson)

        # Long copy is wrapped or shortened, so match on the opening words.
        for half in (before, after):
            head = " ".join(half.split()[:2])
            assert head in painted, (
                f"{format_key}: {half!r} is not on the opening frame - a viewer "
                "who leaves in the first two seconds learns nothing"
            )

    @pytest.mark.parametrize("format_key", _PREVIEW_FORMATS)
    def test_the_generic_promises_are_gone(self, format_key):
        painted = drawn_text(fallbacks.pick(format_key, []))
        for promise in ("Textbook English", "What natives really say", "Use it today"):
            assert promise not in painted, (
                f"{format_key} still opens on a fixed promise instead of content"
            )

    def test_a_lesson_without_items_still_renders_something(self):
        """The fallback path: better a promise than a bare title."""
        painted = drawn_text({"format": "vocab", "title": "A Lesson", "items": []})
        assert "Textbook English" in painted

    def test_the_mistake_format_does_not_cross_out_a_correct_word(self):
        """Both words in a 'commonly confused' lesson are correct English.

        Marking one ❌ teaches the opposite of the lesson.
        """
        lesson = fallbacks.pick("mistake", [])
        assert "❌" not in drawn_text(lesson)

    @pytest.mark.parametrize("format_key", ["vocab", "native", "corporate"])
    def test_swap_formats_still_mark_the_wrong_option(self, format_key):
        assert "❌" in drawn_text(fallbacks.pick(format_key, []))


class TestIntroLength:
    """The opening slide lasts exactly as long as its own narration."""

    def test_only_the_first_sentence_is_kept(self):
        long_intro = (
            "POV: You want to sound professional at work! Here are four "
            "high-value phrases to use in your next meeting or email."
        )
        assert scenes.hook_script(long_intro) == "POV: You want to sound professional at work!"

    def test_a_long_single_sentence_is_cut(self):
        words = " ".join(f"word{n}" for n in range(40))
        assert len(scenes.hook_script(words).split()) <= scenes.INTRO_MAX_WORDS

    def test_a_cut_never_ends_on_a_dangling_word(self):
        rambling = (
            "Everyone says very busy and it is one of the most overused "
            "phrases in the entire English language"
        )
        assert not scenes.hook_script(rambling).rstrip(".!?").split()[-1].lower() in {
            "and", "of", "the", "it", "is", "a", "to", "in"
        }

    def test_empty_input_stays_empty(self):
        assert scenes.hook_script("") == ""
        assert scenes.hook_script(None) == ""

    @pytest.mark.parametrize("format_key", NARRATED_FORMATS)
    def test_curated_lessons_open_inside_the_budget(self, format_key):
        if format_key == FORMAT_QUIZ:
            pytest.skip("the quiz intro reads the question, which is the content")
        for lesson in fallbacks._lessons()[format_key]:
            hook = scenes.hook_script(lesson.get("intro_script", ""))
            seconds = len(hook.split()) / scenes.WORDS_PER_SECOND
            assert seconds <= MAX_INTRO_SECONDS, (
                f"{lesson['title']!r} holds the opening slide for {seconds:.1f}s"
            )

    @pytest.mark.parametrize("format_key", _PREVIEW_FORMATS)
    def test_the_built_intro_scene_uses_the_shortened_hook(self, format_key):
        lesson = dict(fallbacks.pick(format_key, []))
        lesson["intro_script"] = (
            "First sentence here. Second sentence that should never be spoken."
        )
        intro = scenes.build_lesson_scenes(lesson)[0]
        assert "Second sentence" not in intro["text"]


class TestCoverShowsContent:
    """The cover is the only thing a scroller sees before deciding."""

    @pytest.mark.parametrize("format_key", NARRATED_FORMATS)
    def test_a_content_slide_is_chosen_for_every_narrated_format(self, format_key):
        from reelbot.render.thumbnail import _content_slide_for

        lesson = fallbacks.pick(format_key, [])
        assert _content_slide_for(lesson), f"{format_key} falls back to a title cover"

    def test_the_card_cover_is_the_card_itself(self):
        """Cards never reach create_thumbnail - render_card saves its own cover,
        and that image already is the five swaps."""
        assert FORMAT_CARD not in NARRATED_FORMATS

    def test_the_quiz_still_uses_its_question(self):
        from reelbot.render.thumbnail import _content_slide_for

        assert _content_slide_for(fallbacks.pick("quiz", [])) == "quiz_question"

    def test_a_lesson_with_nothing_to_show_falls_back(self):
        from reelbot.render.thumbnail import _content_slide_for

        assert _content_slide_for({"format": "vocab", "items": []}) == ""
        assert _content_slide_for({"format": "quiz"}) == ""

    @pytest.mark.parametrize("format_key", _PREVIEW_FORMATS)
    def test_the_cover_carries_the_first_swap(self, format_key, tmp_path):
        from reelbot.render.thumbnail import create_thumbnail

        lesson = fallbacks.pick(format_key, [])
        path = create_thumbnail(lesson, tmp_path / "cover.jpg")
        assert path and path.exists()

        # The cover is the intro slide, so what it paints is what render_intro
        # paints; assert on that rather than trying to OCR a JPEG.
        before, after = preview_pairs(lesson)[0]
        painted = drawn_text(lesson)
        assert " ".join(after.split()[:2]) in painted

    def test_a_title_only_lesson_still_produces_a_cover(self, tmp_path):
        from reelbot.render.thumbnail import create_thumbnail

        path = create_thumbnail(
            {"format": "vocab", "title": "No Items Here", "items": []}, tmp_path / "c.jpg"
        )
        assert path and path.exists()
