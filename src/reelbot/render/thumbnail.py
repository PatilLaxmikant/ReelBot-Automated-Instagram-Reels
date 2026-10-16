"""Reel cover thumbnail.

The cover is the only thing a scroller sees in the profile grid, and Instagram
crops it to the centre 1080x1350 there - roughly 285px is cut from the top and
bottom. Everything is therefore composed as a measured stack that is centred
inside that crop, rather than at fixed y coordinates.

The stack is measured before it is drawn, so blocks cannot overlap no matter how
long the title runs.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw

from reelbot.formats import FORMAT_QUIZ
from reelbot.render.text import clean_blank, draw_text, text_width, wrap_text
from reelbot.render.theme import (
    ACCENT_BLUE,
    ACCENT_CYAN,
    ACCENT_YELLOW,
    BG_BOTTOM,
    BG_TOP,
    COVER_BOTTOM,
    COVER_PAD,
    COVER_TOP,
    HEIGHT,
    TEXT_MUTED,
    TEXT_WHITE,
    WIDTH,
    FontSet,
    reel_fonts,
)
from reelbot.settings import get_settings

log = logging.getLogger(__name__)

GUTTER = 96
INNER_WIDTH = WIDTH - GUTTER * 2


@dataclass
class Block:
    """One measured element in the vertical stack."""

    height: int
    draw: Callable[[ImageDraw.ImageDraw, int], None]
    gap_after: int = 0


def _fit(text: str, candidates, max_width: int, max_lines: int):
    """Largest candidate face whose wrapped text fits in ``max_lines``."""
    for font in candidates:
        if len(wrap_text(text, font, max_width)) <= max_lines:
            return font
    return candidates[-1]


def _centred(draw: ImageDraw.ImageDraw, y: int, text: str, font, fill) -> None:
    draw_text(draw, ((WIDTH - text_width(text, font)) // 2, y), text, font, fill)


def _paint_background(image: Image.Image) -> None:
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


def _build_blocks(lesson: dict, fonts: FontSet, handle: str) -> list[Block]:
    """Measure every element up front so the stack can be centred as a unit."""
    blocks: list[Block] = []

    # Category badge.
    badge = str(lesson.get("badge", "DAILY ENGLISH")).upper()
    badge_h = fonts.label.size + 30
    badge_w = int(text_width(badge, fonts.label)) + 64

    def draw_badge(draw: ImageDraw.ImageDraw, y: int) -> None:
        x = (WIDTH - badge_w) // 2
        draw.rounded_rectangle(
            [x, y, x + badge_w, y + badge_h], radius=badge_h // 2,
            fill=(30, 58, 138), outline=ACCENT_BLUE, width=3,
        )
        _centred(draw, y + 14, badge, fonts.label, TEXT_WHITE)

    blocks.append(Block(badge_h, draw_badge, gap_after=44))

    # Hook title - the reason someone taps.
    title = clean_blank(str(lesson.get("title", "Level Up Your English")))
    title_font = _fit(title, (fonts.mega, fonts.hero, fonts.title), INNER_WIDTH, 3)
    title_lines = wrap_text(title, title_font, INNER_WIDTH)[:3]
    title_line_h = title_font.size + 18
    title_h = len(title_lines) * title_line_h

    def draw_title(draw: ImageDraw.ImageDraw, y: int) -> None:
        for line in title_lines:
            _centred(draw, y, line, title_font, TEXT_WHITE)
            y += title_line_h

    blocks.append(Block(title_h, draw_title, gap_after=36))

    # Accent rule.
    def draw_rule(draw: ImageDraw.ImageDraw, y: int) -> None:
        draw.rounded_rectangle(
            [(WIDTH - 200) // 2, y, (WIDTH + 200) // 2, y + 10], radius=5, fill=ACCENT_CYAN,
        )

    blocks.append(Block(10, draw_rule, gap_after=40))

    # Subtitle.
    subtitle = str(lesson.get("subtitle") or "Sound natural, not textbook")
    sub_font = _fit(subtitle, (fonts.body, fonts.caption, fonts.small), INNER_WIDTH, 2)
    sub_lines = wrap_text(subtitle, sub_font, INNER_WIDTH)[:2]
    sub_line_h = sub_font.size + 14
    sub_h = len(sub_lines) * sub_line_h

    def draw_subtitle(draw: ImageDraw.ImageDraw, y: int) -> None:
        for line in sub_lines:
            _centred(draw, y, line, sub_font, ACCENT_CYAN)
            y += sub_line_h

    blocks.append(Block(sub_h, draw_subtitle, gap_after=64))

    # Call to action.
    cta = "\U0001F449  TAP TO LEARN"
    cta_font = _fit(cta, (fonts.body, fonts.caption), INNER_WIDTH - 120, 1)
    cta_h = cta_font.size + 44
    cta_w = int(text_width(cta, cta_font)) + 96

    def draw_cta(draw: ImageDraw.ImageDraw, y: int) -> None:
        x = (WIDTH - cta_w) // 2
        draw.rounded_rectangle(
            [x, y, x + cta_w, y + cta_h], radius=cta_h // 2,
            fill=(26, 40, 92), outline=ACCENT_YELLOW, width=4,
        )
        _centred(draw, y + 20, cta, cta_font, ACCENT_YELLOW)

    blocks.append(Block(cta_h, draw_cta, gap_after=40))

    # Brand handle - previously drawn at y=1780, which the grid crop removed.
    handle_font = _fit(handle, (fonts.caption, fonts.small), INNER_WIDTH, 1)

    def draw_handle(draw: ImageDraw.ImageDraw, y: int) -> None:
        _centred(draw, y, handle, handle_font, TEXT_MUTED)

    blocks.append(Block(handle_font.size + 8, draw_handle))
    return blocks


def _render_slide_cover(
    lesson: dict, scene_type: str, fonts: FontSet, handle: str
) -> Image.Image:
    """Build the cover from the reel's own opening slide.

    The account's own numbers drove this: quizzes whose cover showed the actual
    puzzle took 1,188 / 530 / 223 views, while the one quiz that shipped a
    generic "95% Fail This Tricky Test!" title card took 56 - against a median
    of 130 across all reels. An unanswered question is a real curiosity gap; a
    hype claim is not, and neither is a headline.

    Every format now opens on a slide that carries real content (see
    :func:`reelbot.render.slides.render_intro`), so the same treatment applies
    to all of them: the cover shows a swap the viewer can read before tapping.

    The slide is rendered, its content measured, and the whole block recentred
    inside the crop the profile grid keeps.
    """
    from reelbot.render.slides import render_slide

    # Transparent layer so the drawn content's bounding box can be measured.
    layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    scene = {"type": scene_type, "data": lesson, "duration": 3.0}
    render_slide(ImageDraw.Draw(layer), scene, 6.0, fonts)  # 6s = fully revealed

    canvas = Image.new("RGB", (WIDTH, HEIGHT), BG_TOP)
    _paint_background(canvas)

    box = layer.getbbox()
    if box is None:  # nothing drawn; fall back to the stacked cover
        raise ValueError(f"{scene_type} slide rendered empty")

    content = layer.crop(box)
    handle_room = fonts.caption.size + 40
    band_top, band_bottom = COVER_TOP + COVER_PAD, COVER_BOTTOM - COVER_PAD - handle_room

    # Scale down only if the slide is taller than the crop allows.
    available = band_bottom - band_top
    if content.height > available:
        scale = available / content.height
        content = content.resize(
            (max(1, int(content.width * scale)), available), Image.LANCZOS
        )

    x = (WIDTH - content.width) // 2
    y = band_top + max(0, (available - content.height) // 2)
    canvas.paste(content, (x, y), content)

    draw = ImageDraw.Draw(canvas)
    handle_font = _fit(handle, (fonts.caption, fonts.small), INNER_WIDTH, 1)
    _centred(draw, band_bottom + 16, handle, handle_font, TEXT_MUTED)
    return canvas


def _content_slide_for(lesson: dict) -> str:
    """The slide type whose cover would show real content, or ``""``.

    Empty means nothing better than the stacked title cover is available - a
    quiz without a question, or a lesson whose items are missing the fields the
    preview reads.
    """
    from reelbot.audio.scenes import intro_scene_type
    from reelbot.render.slides import preview_pairs

    format_key = str(lesson.get("format") or "")
    if format_key == FORMAT_QUIZ:
        return "quiz_question" if lesson.get("question") else ""
    return intro_scene_type(format_key) if preview_pairs(lesson) else ""


def create_thumbnail(lesson: dict, output: Path) -> Path | None:
    """Render the 1080x1920 cover, returning its path (None on failure)."""
    try:
        fonts = reel_fonts()
        handle = get_settings().brand_handle

        scene_type = _content_slide_for(lesson)
        if scene_type:
            try:
                cover = _render_slide_cover(lesson, scene_type, fonts, handle)
                output.parent.mkdir(parents=True, exist_ok=True)
                cover.save(output, quality=95)
                log.info("Content cover generated from %s: %s", scene_type, output)
                return output
            except Exception as exc:  # noqa: BLE001 - fall back to the stacked cover
                log.warning("Content cover failed (%s); using the title cover.", exc)

        image = Image.new("RGB", (WIDTH, HEIGHT), BG_TOP)
        _paint_background(image)
        draw = ImageDraw.Draw(image)

        blocks = _build_blocks(lesson, fonts, handle)
        total = sum(block.height + block.gap_after for block in blocks)

        # Centre the whole stack inside the part of the cover the grid keeps.
        available = (COVER_BOTTOM - COVER_PAD) - (COVER_TOP + COVER_PAD)
        y = COVER_TOP + COVER_PAD + max(0, (available - total) // 2)

        for block in blocks:
            block.draw(draw, y)
            y += block.height + block.gap_after

        output.parent.mkdir(parents=True, exist_ok=True)
        image.save(output, quality=95)
        log.info("Cover thumbnail generated: %s", output)
        return output

    except Exception as exc:  # noqa: BLE001 - a missing cover must not fail the run
        log.warning("Could not generate cover thumbnail: %s", exc)
        return None
