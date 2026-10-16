"""Text layer: emoji segmentation, blank cleanup, wrapping."""
from __future__ import annotations

import pytest

from reelbot.render.fonts import ROBOTO_BOLD, load
from reelbot.render.text import clean_blank, segment, strip_emoji, text_width, wrap_text


@pytest.fixture(scope="module")
def font():
    return load(ROBOTO_BOLD, 38)


class TestCleanBlank:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("conducive ____ productivity", "conducive _ productivity"),
            ("conducive_productivity", "conducive _ productivity"),
            ("already _ spaced", "already _ spaced"),
            ("", ""),
        ],
    )
    def test_collapses_to_single_blank(self, raw, expected):
        assert clean_blank(raw) == expected

    def test_no_underscore_is_untouched(self):
        assert clean_blank("Nothing to do here") == "Nothing to do here"


class TestSegment:
    def test_splits_emoji_from_text(self):
        assert segment("❌ Stop") == [(True, "❌"), (False, " Stop")]

    def test_keycap_stays_one_token(self):
        tokens = [chunk for is_emoji, chunk in segment("1️⃣ first") if is_emoji]
        assert tokens == ["1️⃣"]

    def test_zwj_sequence_stays_one_token(self):
        tokens = [chunk for is_emoji, chunk in segment("\U0001F468‍\U0001F4BB dev") if is_emoji]
        assert tokens == ["\U0001F468‍\U0001F4BB"]

    def test_skin_tone_modifier_stays_attached(self):
        tokens = [chunk for is_emoji, chunk in segment("\U0001F44D\U0001F3FD ok") if is_emoji]
        assert tokens == ["\U0001F44D\U0001F3FD"]

    def test_adjacent_emoji_are_separate_tokens(self):
        # Separate tokens let glyph coverage be checked per emoji.
        assert [c for is_e, c in segment("❌✅") if is_e] == ["❌", "✅"]

    def test_plain_text_is_one_segment(self):
        assert segment("no emoji here") == [(False, "no emoji here")]

    def test_empty_string(self):
        assert segment("") == []


class TestStripEmoji:
    def test_removes_emoji_and_collapses_space(self):
        assert strip_emoji("❌ Stop ✅ now") == "Stop now"

    def test_plain_text_unchanged(self):
        assert strip_emoji("Stop now") == "Stop now"


class TestWrapText:
    def test_wraps_within_width(self, font):
        lines = wrap_text("word " * 40, font, 600)
        assert len(lines) > 1
        assert all(text_width(line, font) <= 600 for line in lines)

    def test_short_text_is_one_line(self, font):
        assert wrap_text("Short", font, 600) == ["Short"]

    def test_breaks_a_word_wider_than_the_box(self, font):
        lines = wrap_text("Supercalifragilisticexpialidocious", font, 120)
        assert len(lines) > 1
        assert all(text_width(line, font) <= 120 for line in lines)

    def test_empty_text(self, font):
        assert wrap_text("", font, 600) == []

    def test_emoji_counted_in_width(self, font):
        """An emoji must add width, or wrapped lines silently overflow."""
        assert text_width("❌ Stop", font) > text_width(" Stop", font)

    def test_result_is_cached_but_independent(self, font):
        first = wrap_text("word " * 12, font, 400)
        first.append("mutated")
        assert "mutated" not in wrap_text("word " * 12, font, 400)
