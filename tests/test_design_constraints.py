"""Guards on the platform constraints the layout is built around.

These are not aesthetic preferences. Instagram covers fixed bands of the frame
with its own UI, and text below a certain size is unreadable on a phone; both
have measurable effects on completion rate. Encoding them as tests stops a
future layout tweak from quietly reintroducing the old problems.
"""
from __future__ import annotations

import pytest

from reelbot.render import theme
from reelbot.render.components import subtitle_top
from reelbot.render.theme import card_fonts, reel_fonts

# Published guidance quotes a "36pt minimum" for Reels text without stating the
# reference canvas, so it cannot be converted to canvas pixels exactly (1080px
# spans roughly 390pt of phone screen, but that varies by device). These floors
# are therefore set in canvas pixels and verified by eye at phone scale. Their
# job is to stop a regression to the old 30-38px sizes, which were unreadable.
MIN_BODY_PX = 60
MIN_HEADLINE_PX = 100
PREVIOUS_BODY_PX = 38  # what the original design shipped


class TestSafeZones:
    def test_content_clears_the_right_action_column(self):
        assert theme.CONTENT_RIGHT <= theme.WIDTH - theme.UNSAFE_RIGHT

    def test_content_starts_below_the_status_bar(self):
        assert theme.SAFE_TOP >= theme.UNSAFE_TOP

    def test_content_ends_above_the_caption_band(self):
        assert theme.SAFE_BOTTOM <= theme.HEIGHT - theme.UNSAFE_BOTTOM

    def test_side_margins_clear_curved_bezels(self):
        assert theme.CONTENT_LEFT >= 100
        assert theme.WIDTH - theme.CONTENT_RIGHT >= 100

    def test_hook_band_sits_in_the_attention_zone(self):
        assert theme.HOOK_TOP >= theme.UNSAFE_TOP
        assert theme.HOOK_BOTTOM <= theme.HEIGHT // 2

    @pytest.mark.parametrize("fonts", [reel_fonts(), card_fonts()], ids=["reel", "card"])
    def test_subtitle_band_never_enters_the_caption_zone(self, fonts):
        """The old layout drew captions at y=1680, inside Instagram's own UI."""
        assert subtitle_top(fonts) < theme.SAFE_BOTTOM
        assert theme.SAFE_BOTTOM <= theme.HEIGHT - theme.UNSAFE_BOTTOM


class TestTypeScale:
    def test_body_text_is_readable_on_a_phone(self):
        assert reel_fonts().body.size >= MIN_BODY_PX

    def test_body_text_is_well_above_the_old_size(self):
        """The original 38px body was the main reason reels looked cluttered."""
        assert reel_fonts().body.size >= PREVIOUS_BODY_PX * 1.5

    def test_headlines_are_readable_on_a_phone(self):
        fonts = reel_fonts()
        assert fonts.hero.size >= MIN_HEADLINE_PX
        assert fonts.mega.size >= fonts.hero.size

    def test_even_the_smallest_face_beats_the_old_body_size(self):
        assert reel_fonts().small.size >= PREVIOUS_BODY_PX

    def test_scale_is_monotonic(self):
        fonts = reel_fonts()
        sizes = [
            fonts.mega.size, fonts.hero.size, fonts.title.size,
            fonts.body.size, fonts.small.size,
        ]
        assert sizes == sorted(sizes, reverse=True)

    def test_card_scale_is_smaller_than_reel_scale(self):
        # The card packs five rows, so it legitimately runs tighter.
        assert card_fonts().hero.size < reel_fonts().hero.size

    def test_back_compat_aliases_resolve(self):
        fonts = reel_fonts()
        assert fonts.badge is fonts.label
        assert fonts.bold is fonts.body
        assert fonts.subtitle is fonts.caption
