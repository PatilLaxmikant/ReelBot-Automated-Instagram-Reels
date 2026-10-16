"""The single-card format: one dense cheat-sheet image over a music bed.

No voiceover, so the whole video is one static image plus an animated progress
bar. Rows are laid out from the space actually available, so five swaps never
collide regardless of how long the words are.
"""
from __future__ import annotations

import logging
import math
from pathlib import Path

import numpy as np
from moviepy.editor import AudioFileClip, ImageSequenceClip, concatenate_audioclips
from PIL import Image, ImageDraw

from reelbot.audio.assets import ensure_lofi_bgm, ensure_trending_beat
from reelbot.render.text import clean_blank, draw_text, text_width, wrap_text
from reelbot.render.theme import (
    ACCENT_BLUE,
    ACCENT_CYAN,
    ACCENT_GREEN,
    ACCENT_YELLOW,
    HEIGHT,
    TEXT_DIM,
    TEXT_MUTED,
    TEXT_WHITE,
    WIDTH,
    FontSet,
    card_fonts,
)
from reelbot.settings import get_settings
from reelbot.store.paths import reel_path, thumb_path

log = logging.getLogger(__name__)

CARD_X0, CARD_X1 = 60, WIDTH - 60
CARD_Y0, CARD_Y1 = 140, HEIGHT - 100
MAX_ROWS = 5


def _draw_centered(
    draw: ImageDraw.ImageDraw, y: int, text: str, font, fill: tuple[int, int, int]
) -> None:
    draw_text(draw, ((WIDTH - text_width(text, font)) // 2, y), text, font, fill)


def _fit(text: str, max_width: int, candidates, max_lines: int = 1):
    """Largest candidate face whose wrapped text fits in ``max_lines``.

    Cells on this card are narrow, and the words the model returns vary a lot in
    length; sizing per cell prevents the truncation a fixed size produced.
    """
    for font in candidates:
        if len(wrap_text(text, font, max_width)) <= max_lines:
            return font
    return candidates[-1]


def render_card(lesson: dict, fonts: FontSet | None = None) -> Image.Image:
    """Render the full-resolution card image."""
    fonts = fonts or card_fonts()
    settings = get_settings()

    img = Image.new("RGB", (WIDTH, HEIGHT), (10, 14, 26))
    draw = ImageDraw.Draw(img)

    for y in range(0, HEIGHT, 4):
        ratio = y / HEIGHT
        draw.rectangle(
            [(0, y), (WIDTH, y + 4)],
            fill=(
                int(10 * (1 - ratio) + 18 * ratio),
                int(14 * (1 - ratio) + 24 * ratio),
                int(26 * (1 - ratio) + 48 * ratio),
            ),
        )

    draw.rectangle([(0, 0), (WIDTH, 8)], fill=ACCENT_CYAN)
    draw.rounded_rectangle(
        [CARD_X0, CARD_Y0, CARD_X1, CARD_Y1], radius=36,
        fill=(18, 24, 40), outline=(42, 54, 80), width=3,
    )

    # Category badge, centred.
    badge = str(lesson.get("badge", "ENGLISH TIP")).upper()
    badge_w = text_width(badge, fonts.badge) + 50
    badge_h = fonts.badge.size + 20
    badge_x = (WIDTH - badge_w) // 2
    badge_y = CARD_Y0 + 40
    draw.rounded_rectangle(
        [badge_x, badge_y, badge_x + badge_w, badge_y + badge_h], radius=16,
        fill=(30, 58, 138), outline=ACCENT_BLUE, width=2,
    )
    draw_text(draw, (badge_x + 25, badge_y + 9), badge, fonts.badge, TEXT_WHITE)

    # Hero title - the face is chosen so it fits, and the divider follows the
    # real text height rather than a fixed offset (which used to overlap it).
    title = clean_blank(lesson.get("title", "Upgrade Your English"))
    title_width = CARD_X1 - CARD_X0 - 80
    title_font = _fit(title, title_width, (fonts.hero, fonts.title, fonts.body), max_lines=2)
    y = badge_y + badge_h + 30
    for line in wrap_text(title, title_font, title_width)[:2]:
        _draw_centered(draw, y, line, title_font, TEXT_WHITE)
        y += title_font.size + 12

    divider_y = y + 40  # clears descenders on the title's last line
    draw.line([(CARD_X0 + 60, divider_y), (CARD_X1 - 60, divider_y)], fill=(45, 58, 85), width=2)
    draw.line([(WIDTH // 2 - 80, divider_y), (WIDTH // 2 + 80, divider_y)], fill=ACCENT_CYAN, width=3)

    items = (lesson.get("items") or [])[:MAX_ROWS]
    area_top = divider_y + 30
    area_bottom = CARD_Y1 - 150
    available = area_bottom - area_top
    row_pitch = min(210, available // max(len(items), 1))
    box_h = row_pitch - 14
    # Centre the block so a short list does not leave one lopsided gap.
    rows_top = area_top + max(0, (available - row_pitch * len(items)) // 2)

    for idx, item in enumerate(items):
        top = rows_top + idx * row_pitch
        bottom = top + box_h

        draw.rounded_rectangle(
            [CARD_X0 + 30, top, CARD_X1 - 30, bottom], radius=20,
            fill=(14, 20, 36) if idx % 2 == 0 else (12, 17, 30),
            outline=(38, 48, 70), width=2,
        )

        # Index chip.
        chip_x = CARD_X0 + 45
        chip_y = top + (box_h - 40) // 2
        draw.rounded_rectangle([chip_x, chip_y, chip_x + 48, chip_y + 40], radius=10, fill=(28, 38, 58))
        draw_text(draw, (chip_x + 9, chip_y + 6), f"{idx + 1:02d}", fonts.badge, ACCENT_CYAN)

        # Left: the overused phrase, struck through.
        left_x = chip_x + 64
        arrow_x = CARD_X0 + 410
        left_width = arrow_x - left_x - 20
        wrong = str(item.get("wrong", "")).strip()
        wrong_font = _fit(wrong, left_width, (fonts.body, fonts.caption, fonts.small))
        wrong_text = (wrap_text(wrong, wrong_font, left_width) or [wrong])[0]

        draw_text(draw, (left_x, top + 14), "INSTEAD OF:", fonts.small, TEXT_MUTED)
        wrong_y = top + 22 + fonts.small.size
        draw_text(draw, (left_x, wrong_y), wrong_text, wrong_font, (248, 113, 113))
        box = draw.textbbox((left_x, wrong_y), wrong_text, font=wrong_font)
        strike_y = (box[1] + box[3]) // 2
        draw.line(
            [(left_x, strike_y), (left_x + text_width(wrong_text, wrong_font) + 4, strike_y)],
            fill=(239, 68, 68), width=4,
        )

        # Centre: transition arrow, drawn as a polygon because neither Roboto
        # nor Segoe UI Emoji carries a usable arrow glyph.
        arrow_y = top + (box_h - 40) // 2
        draw.rounded_rectangle([arrow_x, arrow_y, arrow_x + 50, arrow_y + 40], radius=12, fill=(25, 42, 70))
        mid_y = arrow_y + 20
        draw.line([(arrow_x + 14, mid_y), (arrow_x + 32, mid_y)], fill=ACCENT_CYAN, width=4)
        draw.polygon(
            [(arrow_x + 28, mid_y - 9), (arrow_x + 40, mid_y), (arrow_x + 28, mid_y + 9)],
            fill=ACCENT_CYAN,
        )

        # Right: the natural alternative.
        box_x0 = arrow_x + 68
        box_x1 = CARD_X1 - 45
        draw.rounded_rectangle(
            [box_x0, top + 14, box_x1, bottom - 14], radius=16,
            fill=(12, 38, 26), outline=ACCENT_GREEN, width=2,
        )
        draw_text(draw, (box_x0 + 18, top + 20), "SAY THIS:", fonts.small, ACCENT_GREEN)

        right = str(item.get("right", "")).strip()
        emoji = str(item.get("emoji", "")).strip()
        label = f"{right} {emoji}".strip() if emoji else right
        right_width = box_x1 - box_x0 - 36
        right_font = _fit(label, right_width, (fonts.title, fonts.body, fonts.caption, fonts.small))
        right_text = (wrap_text(label, right_font, right_width) or [label])[0]
        draw_text(
            draw, (box_x0 + 18, top + 30 + fonts.small.size), right_text, right_font, TEXT_WHITE,
        )

    # Save CTA.
    cta = str(lesson.get("footer_cta") or "\U0001F4BE SAVE THIS CARD FOR PRACTICE")
    cta_y = CARD_Y1 - 105
    cta_w = max(640, int(text_width(cta, fonts.badge)) + 80)
    cta_x = (WIDTH - cta_w) // 2
    draw.rounded_rectangle(
        [cta_x, cta_y, cta_x + cta_w, cta_y + 70], radius=20,
        fill=(23, 37, 84), outline=ACCENT_YELLOW, width=3,
    )
    _draw_centered(draw, cta_y + 18, cta, fonts.badge, ACCENT_YELLOW)

    # Brand handle (was a hard-coded "@yourchannel" placeholder).
    handle = f"Follow {settings.brand_handle} for Daily English Tips"
    handle_font = _fit(handle, WIDTH - 120, (fonts.small, fonts.label))
    _draw_centered(draw, HEIGHT - 72, handle, handle_font, TEXT_DIM)
    draw.rectangle([(0, HEIGHT - 8), (WIDTH, HEIGHT)], fill=ACCENT_CYAN)
    return img


def _music_bed(duration: float) -> AudioFileClip:
    """A looped, faded music bed exactly ``duration`` seconds long."""
    path = ensure_trending_beat()
    if not path.exists():
        log.warning("Trending beat unavailable; falling back to lo-fi bed.")
        path = ensure_lofi_bgm()

    clip = AudioFileClip(str(path))
    if clip.duration < duration:
        clip = concatenate_audioclips([clip] * (math.ceil(duration / clip.duration) + 1))
    clip = clip.subclip(0, duration).volumex(0.70)

    from moviepy.audio.fx import all as afx  # local import keeps module load cheap

    clip = afx.audio_fadein(clip, 0.4)
    return afx.audio_fadeout(clip, min(1.2, duration * 0.2))


def create_card_video(lesson: dict, safe_name: str, duration: float, fps: int) -> tuple[Path, Path]:
    """Render the card reel and its thumbnail.

    Returns:
        ``(video_path, thumbnail_path)``.
    """
    log.info("Rendering card reel (%.0fs, music only) ...", duration)
    card = render_card(lesson)

    thumb = thumb_path(safe_name)
    thumb.parent.mkdir(parents=True, exist_ok=True)
    card.save(thumb, quality=98)
    log.info("Card thumbnail saved: %s", thumb)

    # A static image plus a moving progress bar: only the bar needs redrawing,
    # and the frame count is small enough to hold in memory.
    total_frames = int(duration * fps)
    frames = []
    for index in range(total_frames):
        frame = card.copy()
        bar = ImageDraw.Draw(frame)
        bar.rectangle([(0, 0), (int(WIDTH * (index + 1) / total_frames), 10)], fill=ACCENT_CYAN)
        frames.append(np.asarray(frame))

    music = None
    video = None
    final = None
    try:
        music = _music_bed(duration)
        video = ImageSequenceClip(frames, fps=fps)
        final = video.set_audio(music)
        out = reel_path(safe_name)
        final.write_videofile(
            str(out),
            fps=fps,
            codec="libx264",
            audio_codec="aac",
            bitrate="10000k",
            ffmpeg_params=["-crf", "17", "-pix_fmt", "yuv420p"],
            preset="fast",
            logger=None,
        )
        log.info("Card reel created: %s", out)
        return out, thumb
    finally:
        for clip in (final, video, music):
            try:
                if clip is not None:
                    clip.close()
            except Exception:  # noqa: BLE001
                pass
