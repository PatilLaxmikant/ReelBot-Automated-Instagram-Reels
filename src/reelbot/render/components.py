"""Reusable frame furniture: background, header, subtitle band, progress bar.

Placement here is governed by the safe zones in :mod:`reelbot.render.theme`.
The subtitle band in particular used to sit at y=1680, inside the 280px strip
Instagram covers with the caption and audio attribution.
"""
from __future__ import annotations

import functools
import math

from PIL import Image, ImageDraw

from reelbot.render import probe
from reelbot.render.anim import lerp_colour, reveal
from reelbot.render.text import draw_text, text_width, wrap_text
from reelbot.render.theme import (
    ACCENT_CYAN,
    BG_BOTTOM,
    BG_TOP,
    CONTENT_LEFT,
    CONTENT_RIGHT,
    CONTENT_WIDTH,
    HEIGHT,
    PANEL_DARK,
    SAFE_BOTTOM,
    SAFE_TOP,
    TEXT_WHITE,
    WIDTH,
    FontSet,
)

_SHIFT_RANGE = 10


def gradient_shift(frame_idx: int) -> int:
    return int(math.sin(frame_idx / 24.0) * _SHIFT_RANGE)


# Only ~19 distinct shifts occur, so this caches at roughly 120 MB and never grows.
@functools.lru_cache(maxsize=24)
def _gradient_base(shift: int) -> Image.Image:
    """Pre-render one gradient variant. Cached across the whole run."""
    img = Image.new("RGB", (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(img)
    for y in range(0, HEIGHT, 6):
        ratio = y / HEIGHT
        r = int(BG_TOP[0] * (1 - ratio) + BG_BOTTOM[0] * ratio + shift)
        g = int(BG_TOP[1] * (1 - ratio) + BG_BOTTOM[1] * ratio)
        b = int(BG_TOP[2] * (1 - ratio) + BG_BOTTOM[2] * ratio + shift)
        draw.rectangle(
            [(0, y), (WIDTH, y + 6)],
            fill=(max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b))),
        )
    return img


def new_frame(frame_idx: int) -> Image.Image:
    """A fresh canvas with the animated gradient already painted."""
    return _gradient_base(gradient_shift(frame_idx)).copy()


def frame_background(frame_idx: int) -> tuple[int, int, int]:
    """Approximate mid-frame background colour, used to fake text fades."""
    shift = gradient_shift(frame_idx)
    return (
        max(0, min(255, (BG_TOP[0] + BG_BOTTOM[0]) // 2 + shift)),
        (BG_TOP[1] + BG_BOTTOM[1]) // 2,
        max(0, min(255, (BG_TOP[2] + BG_BOTTOM[2]) // 2 + shift)),
    )


def draw_header(draw: ImageDraw.ImageDraw, badge: str, step: str, fonts: FontSet) -> None:
    """Category eyebrow on the left, progress counter on the right."""
    font = fonts.label
    pad_x, pad_y = 26, 12
    top = SAFE_TOP

    badge_w = text_width(badge, font) + pad_x * 2
    badge_h = font.size + pad_y * 2
    draw.rounded_rectangle(
        [CONTENT_LEFT, top, CONTENT_LEFT + badge_w, top + badge_h],
        radius=20, fill=(30, 58, 138), outline=(59, 130, 246), width=3,
    )
    probe.note_panel((CONTENT_LEFT, top, CONTENT_LEFT + badge_w, top + badge_h))
    draw_text(draw, (CONTENT_LEFT + pad_x, top + pad_y), badge, font, TEXT_WHITE)

    if not step:
        return
    step_w = text_width(step, font) + pad_x * 2
    step_x = CONTENT_RIGHT - step_w
    draw.rounded_rectangle(
        [step_x, top, step_x + step_w, top + badge_h],
        radius=20, fill=(30, 41, 59), outline=(71, 85, 105), width=3,
    )
    probe.note_panel((step_x, top, step_x + step_w, top + badge_h))
    draw_text(draw, (step_x + pad_x, top + pad_y), step, font, ACCENT_CYAN)


def header_bottom(fonts: FontSet) -> int:
    return SAFE_TOP + fonts.label.size + 24


def draw_subtitles(
    draw: ImageDraw.ImageDraw, current_time: float, cues: list[dict], fonts: FontSet
) -> None:
    """Karaoke-style caption band, sitting clear of Instagram's own UI.

    Anchored so its lower edge lands on SAFE_BOTTOM and it grows upward, which
    keeps a two-line caption out of the 280px zone the app covers.
    """
    active = ""
    for cue in cues:
        if cue["start"] <= current_time <= cue["end"]:
            active = cue["text"]
            break
    if not active:
        return

    font = fonts.caption
    lines = wrap_text(active, font, CONTENT_WIDTH - 80)[:2]
    line_h = font.size + 14
    pill_h = 40 + len(lines) * line_h
    pill_bottom = SAFE_BOTTOM
    pill_top = pill_bottom - pill_h

    draw.rounded_rectangle(
        [CONTENT_LEFT, pill_top, CONTENT_RIGHT, pill_bottom],
        radius=26, fill=PANEL_DARK, outline=(51, 65, 85), width=3,
    )
    y = pill_top + 20
    for line in lines:
        draw_text(draw, ((WIDTH - text_width(line, font)) // 2, y), line, font, TEXT_WHITE)
        y += line_h


def subtitle_top(fonts: FontSet) -> int:
    """Highest y a two-line caption band can reach - slides must stay above."""
    return SAFE_BOTTOM - (40 + 2 * (fonts.caption.size + 14))


def draw_progress(draw: ImageDraw.ImageDraw, ratio: float) -> None:
    """Thin playback bar pinned to the very top edge."""
    width = int(WIDTH * max(0.0, min(1.0, ratio)))
    if width > 0:
        draw.rectangle([(0, 0), (width, 12)], fill=ACCENT_CYAN)


def panel(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    *,
    fill: tuple[int, int, int],
    outline: tuple[int, int, int],
    amount: float = 1.0,
    radius: int = 32,
    width: int = 4,
) -> None:
    """A rounded panel that fades in with ``amount`` (0..1)."""
    if amount <= 0.01:
        return
    background = (12, 15, 30)
    draw.rounded_rectangle(
        list(box),
        radius=radius,
        fill=lerp_colour(background, fill, amount),
        outline=lerp_colour(background, outline, amount),
        width=width,
    )
    probe.note_panel(box)


def eyebrow(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    fonts: FontSet,
    colour: tuple[int, int, int],
    scene_time: float,
    at: float,
    background: tuple[int, int, int] = (18, 22, 38),
) -> None:
    """Small all-caps label that fades and rises into place."""
    amount = reveal(scene_time, at)
    if amount <= 0.01:
        return
    x, y = xy
    y += int(24 * (1.0 - amount))
    draw_text(draw, (x, y), text, fonts.label, lerp_colour(background, colour, amount))
