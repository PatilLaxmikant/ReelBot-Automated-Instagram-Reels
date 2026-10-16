"""Canvas geometry, safe zones, colour palette and font sets.

Two things here are driven by platform constraints rather than taste:

*Safe zones* - Instagram's own UI covers the bottom 280px (caption + audio),
the top 150px (status bar and controls) and a 90px strip on the right
(like/comment/share). Text placed in those bands is measurably worse for
completion rate, so nothing important is drawn there.

*Type scale* - a 1080px-wide canvas displays on a phone roughly 390pt wide, so
canvas pixels are ~2.8x smaller than they look on a desktop monitor. The old
30-56px sizes rendered at roughly 11-20pt on a phone, well under the ~36pt
minimum for comfortable mobile reading. Sizes below are ~2.5x larger, which
also forces far less text per slide.
"""
from __future__ import annotations

import functools
from dataclasses import dataclass

from PIL import ImageFont

from reelbot.render.fonts import ROBOTO_BOLD, ROBOTO_REGULAR, load

# --- Canvas --------------------------------------------------------------
WIDTH = 1080
HEIGHT = 1920

# --- Instagram safe zones ------------------------------------------------
UNSAFE_TOP = 150       # status bar, camera/filter controls
UNSAFE_BOTTOM = 280    # caption text and audio attribution
UNSAFE_RIGHT = 90      # like / comment / share column

SAFE_TOP = 180
SAFE_BOTTOM = HEIGHT - UNSAFE_BOTTOM - 20      # 1620
SIDE_MARGIN = 108                               # clears curved bezels
CONTENT_LEFT = SIDE_MARGIN
CONTENT_RIGHT = WIDTH - SIDE_MARGIN             # 972, also clears the action strip
CONTENT_WIDTH = CONTENT_RIGHT - CONTENT_LEFT    # 864

#: Where the primary hook belongs - highest-attention band of the frame.
HOOK_TOP = 200
HOOK_BOTTOM = 600

# --- Cover / thumbnail crop ---------------------------------------------
# The profile grid does not show the whole 9:16 cover. Instagram crops it to
# the centre 1080x1350 (4:5), cutting ~285px off the top and bottom, so a
# cover's title and handle must live inside this band or they vanish in the grid.
COVER_CROP_HEIGHT = 1350
COVER_TOP = (HEIGHT - COVER_CROP_HEIGHT) // 2          # 285
COVER_BOTTOM = COVER_TOP + COVER_CROP_HEIGHT           # 1635
COVER_PAD = 48                                          # breathing room inside the crop

# --- Palette -------------------------------------------------------------
BG_TOP = (10, 12, 22)
BG_BOTTOM = (24, 18, 56)
CARD_DARK = (20, 27, 45)
CARD_BORDER = (45, 58, 85)
PANEL_DARK = (15, 23, 42)

ACCENT_BLUE = (59, 130, 246)
ACCENT_GREEN = (34, 197, 94)
ACCENT_RED = (239, 68, 68)
ACCENT_YELLOW = (250, 204, 21)
ACCENT_ORANGE = (249, 115, 22)
ACCENT_CYAN = (34, 211, 238)
ACCENT_PINK = (244, 114, 182)

TEXT_WHITE = (255, 255, 255)
TEXT_MUTED = (148, 163, 184)
TEXT_DIM = (100, 116, 139)

WRONG_BG = (46, 16, 24)
WRONG_BORDER = (225, 45, 45)
WRONG_TEXT = (252, 130, 130)
RIGHT_BG = (8, 44, 30)
RIGHT_BORDER = (34, 197, 94)
RIGHT_TEXT = (110, 245, 170)
RIGHT_BADGE_BG = (16, 78, 44)

BRAND_HANDLE = "@DailyEnglishTips"


@dataclass(frozen=True)
class FontSet:
    """Sized faces for one render target.

    ``mega`` is for a single hero word; ``label`` is for small all-caps eyebrow
    text. Everything between is body copy.
    """

    mega: ImageFont.FreeTypeFont
    hero: ImageFont.FreeTypeFont
    title: ImageFont.FreeTypeFont
    body: ImageFont.FreeTypeFont
    label: ImageFont.FreeTypeFont
    caption: ImageFont.FreeTypeFont
    small: ImageFont.FreeTypeFont

    # Back-compat aliases so existing call sites keep working.
    @property
    def badge(self) -> ImageFont.FreeTypeFont:
        return self.label

    @property
    def bold(self) -> ImageFont.FreeTypeFont:
        return self.body

    @property
    def subtitle(self) -> ImageFont.FreeTypeFont:
        return self.caption

    @property
    def regular(self) -> ImageFont.FreeTypeFont:
        return self.caption


@functools.lru_cache(maxsize=4)
def reel_fonts() -> FontSet:
    """Type scale for narrated reels. ~2.5x the previous sizes."""
    return FontSet(
        mega=load(ROBOTO_BOLD, 140),
        hero=load(ROBOTO_BOLD, 108),
        title=load(ROBOTO_BOLD, 84),
        body=load(ROBOTO_BOLD, 64),
        label=load(ROBOTO_BOLD, 46),
        caption=load(ROBOTO_REGULAR, 60),
        small=load(ROBOTO_REGULAR, 48),
    )


@functools.lru_cache(maxsize=4)
def card_fonts() -> FontSet:
    """Slightly tighter scale for the denser five-row card."""
    return FontSet(
        mega=load(ROBOTO_BOLD, 104),
        hero=load(ROBOTO_BOLD, 86),
        title=load(ROBOTO_BOLD, 68),
        body=load(ROBOTO_BOLD, 58),
        label=load(ROBOTO_BOLD, 40),
        caption=load(ROBOTO_REGULAR, 46),
        small=load(ROBOTO_REGULAR, 38),
    )
