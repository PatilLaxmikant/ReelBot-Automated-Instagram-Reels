"""Emoji-aware text measurement, wrapping and drawing.

Roboto carries no emoji glyphs, so every emoji drawn with it rendered as a
hollow ``.notdef`` box. These helpers split a string into text and emoji runs,
measure and draw each run with the font that actually has the glyph, and cache
the (expensive) wrap results.
"""
from __future__ import annotations

import functools
import re
from pathlib import Path

from PIL import ImageDraw, ImageFont

from reelbot.render import probe
from reelbot.render.fonts import emoji_font, emoji_font_covers, has_emoji_font

# Codepoint blocks that a colour-emoji font should own rather than Roboto.
_EMOJI_CHARS = (
    "\U0001F000-\U0001FAFF"  # emoticons, pictographs, transport, supplemental, extended-A
    "⌀-⏿"          # technical: watch, hourglass, timer, media controls
    "☀-➿"          # misc symbols + dingbats: sun, check, cross, sparkles, arrows
    "⤀-⥿"          # supplemental arrows
    "⬀-⯿"          # stars, bold arrows
    "©®™ℹ"
)
_MODIFIER = "[️︎\U0001F3FB-\U0001F3FF]*"
_BASE = f"[{_EMOJI_CHARS}]{_MODIFIER}"
# One token at a time (not a greedy run) so glyph coverage can be checked per
# emoji. Keycap sequences (1️⃣) start with an ASCII digit and need their own branch.
EMOJI_RE = re.compile(f"(?:[#*0-9]️?⃣|{_BASE}(?:‍{_BASE})*)")

#: Emoji glyphs sit slightly higher than Roboto's cap height; nudge them down.
_EMOJI_Y_NUDGE = 0.08


def strip_emoji(text: str) -> str:
    """Remove every emoji run. Used for filenames and speech synthesis."""
    if not text:
        return ""
    return re.sub(r"\s{2,}", " ", EMOJI_RE.sub("", str(text))).strip()


def clean_blank(text: str) -> str:
    """Collapse quiz blanks (``____``) to a single spaced ``_``."""
    if not text:
        return ""
    cleaned = re.sub(r"_{2,}", "_", str(text))
    cleaned = re.sub(r"(\w)_", r"\1 _", cleaned)
    cleaned = re.sub(r"_(\w)", r"_ \1", cleaned)
    return cleaned.strip()


def segment(text: str) -> list[tuple[bool, str]]:
    """Split ``text`` into ``(is_emoji, chunk)`` runs in original order."""
    if not text:
        return []
    parts: list[tuple[bool, str]] = []
    cursor = 0
    for match in EMOJI_RE.finditer(text):
        if match.start() > cursor:
            parts.append((False, text[cursor:match.start()]))
        parts.append((True, match.group()))
        cursor = match.end()
    if cursor < len(text):
        parts.append((False, text[cursor:]))
    return parts


def _font_key(font: ImageFont.FreeTypeFont) -> tuple[str, int]:
    """A hashable identity for a loaded font, for cache keys."""
    return (str(getattr(font, "path", "?")), int(getattr(font, "size", 0)))


def text_width(text: str, font: ImageFont.FreeTypeFont) -> float:
    """Width of ``text`` in pixels, accounting for emoji drawn in another font."""
    if not text:
        return 0.0
    if not has_emoji_font():
        return font.getlength(text)

    total = 0.0
    for is_emoji, chunk in segment(text):
        if is_emoji and emoji_font_covers(chunk, font.size):
            try:
                total += emoji_font(font.size).getlength(chunk)
                continue
            except (OSError, ValueError):
                pass
        total += font.getlength(chunk)
    return total


def draw_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[float, float],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int],
) -> float:
    """Draw ``text`` at ``xy``, rendering emoji runs in full colour.

    Returns the total advance width so callers can chain runs if they need to.
    """
    if not text:
        return 0.0

    x, y = xy
    if not has_emoji_font():
        draw.text((x, y), text, font=font, fill=fill)
        advance = font.getlength(text)
        _record(draw, (x, y), text, font, advance)
        return advance

    start_x = x
    for is_emoji, chunk in segment(text):
        # Only route through the emoji font when it genuinely has the glyph;
        # otherwise Roboto draws it (or draws its own .notdef, which is no
        # worse) rather than the emoji font's hollow box.
        if is_emoji and emoji_font_covers(chunk, font.size):
            efont = emoji_font(font.size)
            try:
                # embedded_color pulls the font's own COLR/CBDT layers, so the
                # `fill` colour is deliberately ignored for emoji runs.
                draw.text(
                    (x, y + font.size * _EMOJI_Y_NUDGE),
                    chunk,
                    font=efont,
                    embedded_color=True,
                )
                x += efont.getlength(chunk)
                continue
            except (OSError, ValueError):
                pass  # fall through and draw as plain text
        draw.text((x, y), chunk, font=font, fill=fill)
        x += font.getlength(chunk)

    _record(draw, (start_x, y), text, font, x - start_x)
    return x - start_x


def _record(draw, xy, text: str, font, advance: float) -> None:
    """Hand the drawn text's ink box to the layout probe, if one is active."""
    if not probe.is_recording():
        return
    x, y = xy
    try:
        ink = draw.textbbox((x, y), text, font=font)
        top, bottom = ink[1], ink[3]
    except (OSError, ValueError):
        # Fall back to the measured ink ratio for this face.
        top, bottom = y + font.size * 0.30, y + font.size * 1.28
    probe.note_text((x, top, x + advance, bottom), text)


@functools.lru_cache(maxsize=4096)
def _wrap_cached(text: str, font_key: tuple[str, int], max_width: int) -> tuple[str, ...]:
    font = ImageFont.truetype(font_key[0], font_key[1])
    return tuple(_wrap_uncached(text, font, max_width))


def _wrap_uncached(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    words = str(text).strip().split()
    lines: list[str] = []
    current: list[str] = []

    for word in words:
        candidate = " ".join(current + [word])
        if text_width(candidate, font) <= max_width:
            current.append(word)
            continue

        if current:
            lines.append(" ".join(current))
            current = []

        if text_width(word, font) <= max_width:
            current = [word]
            continue

        # A single word wider than the line box: break it character by character.
        chunk = ""
        for char in word:
            if text_width(chunk + char, font) <= max_width:
                chunk += char
            else:
                if chunk:
                    lines.append(chunk)
                chunk = char
        if chunk:
            current = [chunk]

    if current:
        lines.append(" ".join(current))
    return lines or ([str(text).strip()] if str(text).strip() else [])


def wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Wrap ``text`` to ``max_width`` pixels, splitting over-long words.

    Results are cached: the renderer re-wraps the same strings for every one of
    the ~1,150 frames in a reel.
    """
    if not text:
        return []
    path = Path(str(getattr(font, "path", "")))
    if not path.exists():
        return _wrap_uncached(text, font, max_width)
    return list(_wrap_cached(str(text), _font_key(font), int(max_width)))
