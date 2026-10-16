"""Story backdrop for resharing a published reel.

Resharing a new reel to your story puts it in front of existing followers
immediately, and their early engagement is what the algorithm reads first.

The backdrop has to say what the reel *is*. An earlier version drew only a
"NEW TODAY" badge and a tap prompt, which made every story byte-identical
regardless of what was posted - a viewer had no reason to tap. It now carries
the lesson's own hook, and a per-format accent so consecutive stories do not
look like the same image twice.

The reshared post is placed explicitly (see :data:`STICKER`) rather than left on
instagrapi's centred default, because the default band leaves no room for a
readable headline above it.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

from reelbot.formats import (
    FORMAT_CARD,
    FORMAT_CORPORATE,
    FORMAT_MISTAKE,
    FORMAT_NATIVE,
    FORMAT_QUIZ,
    FORMAT_VOCAB,
    get_spec,
)
from reelbot.render.text import clean_blank, draw_text, strip_emoji, text_width, wrap_text
from reelbot.render.theme import (
    ACCENT_BLUE,
    ACCENT_CYAN,
    ACCENT_GREEN,
    ACCENT_ORANGE,
    ACCENT_PINK,
    ACCENT_YELLOW,
    BG_BOTTOM,
    BG_TOP,
    HEIGHT,
    TEXT_WHITE,
    WIDTH,
    reel_fonts,
)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class StickerBox:
    """Where the reshared reel is placed, in Instagram's 0-1 coordinates.

    ``y`` is the centre of the box, not its top.
    """

    x: float = 0.5
    y: float = 0.575
    width: float = 0.74
    height: float = 0.50

    @property
    def top_px(self) -> int:
        return int((self.y - self.height / 2) * HEIGHT)

    @property
    def bottom_px(self) -> int:
        return int((self.y + self.height / 2) * HEIGHT)


#: Pushed below centre so a real headline fits above it.
STICKER = StickerBox()

#: Story UI: profile row above, reply bar below.
STORY_SAFE_TOP = 200
STORY_SAFE_BOTTOM = 1700

GUTTER = 90
INNER = WIDTH - GUTTER * 2

#: Per-format accent and tap prompt. Both make the story specific to the reel.
_STYLE: dict[str, tuple[tuple[int, int, int], str]] = {
    FORMAT_QUIZ: (ACCENT_YELLOW, "Can you solve it?"),
    FORMAT_VOCAB: (ACCENT_GREEN, "Tap to learn it"),
    FORMAT_NATIVE: (ACCENT_CYAN, "Hear how natives say it"),
    FORMAT_MISTAKE: (ACCENT_ORANGE, "Don't get this wrong"),
    FORMAT_CORPORATE: (ACCENT_BLUE, "Tap for the phrase"),
    FORMAT_CARD: (ACCENT_PINK, "Save this one"),
}


def style_for(format_key: str) -> tuple[tuple[int, int, int], str]:
    return _STYLE.get(format_key, (ACCENT_CYAN, "Tap to watch"))


def _fit(text: str, candidates, max_width: int, max_lines: int = 1):
    for font in candidates:
        if len(wrap_text(text, font, max_width)) <= max_lines:
            return font
    return candidates[-1]


def _centred(draw: ImageDraw.ImageDraw, y: int, text: str, font, fill) -> None:
    draw_text(draw, ((WIDTH - text_width(text, font)) // 2, y), text, font, fill)


def create_story_background(lesson: dict, output: Path) -> Path:
    """Render the 1080x1920 backdrop the reshared reel sits on top of."""
    fonts = reel_fonts()
    format_key = str(lesson.get("format") or "")
    accent, prompt = style_for(format_key)
    badge = str(lesson.get("badge") or (get_spec(format_key).badge if format_key else "NEW TODAY"))

    image = Image.new("RGB", (WIDTH, HEIGHT), BG_TOP)
    draw = ImageDraw.Draw(image)
    for y in range(0, HEIGHT, 4):
        ratio = y / HEIGHT
        draw.rectangle(
            [(0, y), (WIDTH, y + 4)],
            fill=(
                int(BG_TOP[0] * (1 - ratio) + BG_BOTTOM[0] * ratio),
                int(BG_TOP[1] * (1 - ratio) + BG_BOTTOM[1] * ratio),
                int(BG_TOP[2] * (1 - ratio) + BG_BOTTOM[2] * ratio),
            ),
        )

    # --- Above the sticker: the format badge, then the reel's own hook.
    top_limit = STICKER.top_px - 18
    badge_font = fonts.label
    badge_w = int(text_width(badge, badge_font)) + 60
    badge_h = badge_font.size + 24
    badge_x = (WIDTH - badge_w) // 2
    draw.rounded_rectangle(
        [badge_x, STORY_SAFE_TOP, badge_x + badge_w, STORY_SAFE_TOP + badge_h],
        radius=badge_h // 2, fill=(22, 28, 44), outline=accent, width=3,
    )
    _centred(draw, STORY_SAFE_TOP + 11, badge, badge_font, accent)

    title = clean_blank(str(lesson.get("title") or "New English lesson"))
    title_top = STORY_SAFE_TOP + badge_h + 26
    room = top_limit - title_top
    title_font = _fit(title, (fonts.hero, fonts.title, fonts.body, fonts.caption), INNER, 3)
    # Shrink until the wrapped hook genuinely fits the band above the sticker.
    for candidate in (fonts.hero, fonts.title, fonts.body, fonts.caption, fonts.small):
        lines = wrap_text(title, candidate, INNER)
        if len(lines) * (candidate.size + 10) <= room:
            title_font = candidate
            break

    line_h = title_font.size + 10
    y = title_top + max(0, (room - len(wrap_text(title, title_font, INNER)) * line_h) // 2)
    for line in wrap_text(title, title_font, INNER):
        if y + line_h > top_limit:
            break
        _centred(draw, y, line, title_font, TEXT_WHITE)
        y += line_h

    # --- Below the sticker: the format's own tap prompt, then the handle.
    bottom_room = STORY_SAFE_BOTTOM - STICKER.bottom_px - 24
    prompt_font = next(
        (f for f in (fonts.title, fonts.body, fonts.caption) if f.size + 38 <= bottom_room),
        fonts.small,
    )
    pill_w = int(text_width(prompt, prompt_font)) + 96
    pill_h = min(prompt_font.size + 38, max(56, bottom_room - 46))
    pill_x = (WIDTH - pill_w) // 2
    pill_y = STICKER.bottom_px + 20
    draw.rounded_rectangle(
        [pill_x, pill_y, pill_x + pill_w, pill_y + pill_h],
        radius=pill_h // 2, fill=(20, 26, 42), outline=accent, width=4,
    )
    _centred(
        draw, pill_y + (pill_h - prompt_font.size) // 2 - int(prompt_font.size * 0.15),
        prompt, prompt_font, accent,
    )

    # No handle here on purpose: Instagram already prints the account name at
    # the top of every story, and the space below the sticker is too tight to
    # repeat it without crowding the tap prompt.

    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, quality=95)
    log.info("Story backdrop generated: %s", output)
    return output


def story_path(safe_name: str) -> Path:
    from reelbot.store.paths import REELS_DIR

    return REELS_DIR / f"story_{strip_emoji(safe_name) or safe_name}.jpg"
