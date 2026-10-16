"""Font discovery and caching.

Text is drawn in Roboto; emoji are drawn in a colour-emoji font (Segoe UI Emoji
on Windows, Noto Color Emoji elsewhere) so they render as artwork rather than
as ``.notdef`` boxes.
"""
from __future__ import annotations

import functools
import logging
import shutil
from pathlib import Path

import requests
from PIL import ImageFont

from reelbot.store.paths import FONT_DIR, PROJECT_ROOT

log = logging.getLogger(__name__)

ROBOTO_BOLD = "Roboto-Bold.ttf"
ROBOTO_REGULAR = "Roboto-Regular.ttf"

_ROBOTO_URLS = {
    ROBOTO_BOLD: "https://github.com/googlefonts/roboto/raw/main/src/hinted/Roboto-Bold.ttf",
    ROBOTO_REGULAR: "https://github.com/googlefonts/roboto/raw/main/src/hinted/Roboto-Regular.ttf",
}

#: Colour-emoji fonts, most preferred first.
_EMOJI_CANDIDATES = (
    Path("C:/Windows/Fonts/seguiemj.ttf"),                              # Windows
    Path("/System/Library/Fonts/Apple Color Emoji.ttc"),                # macOS
    Path("/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"),          # Debian/Ubuntu
    Path("/usr/share/fonts/google-noto-emoji/NotoColorEmoji.ttf"),      # Fedora
)


@functools.lru_cache(maxsize=8)
def font_file(name: str = ROBOTO_BOLD) -> str:
    """Resolve a Roboto file, downloading it once if it is not bundled.

    Looks in ``assets/fonts/`` first, then the legacy project-root location, so
    the two .ttf files already sitting in the repo keep working.
    """
    bundled = FONT_DIR / name
    if bundled.exists():
        return str(bundled)

    legacy = PROJECT_ROOT / name
    if legacy.exists():
        FONT_DIR.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(legacy, bundled)
            return str(bundled)
        except OSError:
            return str(legacy)

    url = _ROBOTO_URLS.get(name)
    if not url:
        raise FileNotFoundError(f"No source known for font {name!r}")

    log.info("Downloading font %s ...", name)
    FONT_DIR.mkdir(parents=True, exist_ok=True)
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    bundled.write_bytes(response.content)
    log.info("Font saved: %s", bundled)
    return str(bundled)


@functools.lru_cache(maxsize=1)
def emoji_font_path() -> str | None:
    """Absolute path to a colour-emoji font, or None if the system has none."""
    for candidate in _EMOJI_CANDIDATES:
        if candidate.exists():
            return str(candidate)
    log.warning(
        "No colour-emoji font found; emoji will be stripped from rendered frames."
    )
    return None


def has_emoji_font() -> bool:
    return emoji_font_path() is not None


@functools.lru_cache(maxsize=64)
def emoji_font(size: int) -> ImageFont.FreeTypeFont:
    """A colour-emoji font sized to sit alongside ``size``-px body text."""
    path = emoji_font_path()
    if path is None:
        raise FileNotFoundError("No colour-emoji font available")
    return ImageFont.truetype(path, int(size))


#: A Private Use Area codepoint no font defines, used as the ".notdef" sample.
_NOTDEF_PROBE = ""


@functools.lru_cache(maxsize=2048)
def emoji_font_covers(token: str, size: int) -> bool:
    """True if the emoji font actually has a glyph for ``token``.

    Segoe UI Emoji covers most but not all of the dingbat block - ``➔`` for
    instance renders as a hollow box. Comparing the rendered bitmap against a
    known-missing codepoint catches those so the caller can fall back to Roboto.
    """
    try:
        font = emoji_font(size)
        notdef = _render_probe(font, _NOTDEF_PROBE, size)
        glyph = _render_probe(font, token, size)
    except (OSError, ValueError, FileNotFoundError):
        return False
    return bool(glyph) and glyph != notdef


def _render_probe(font: ImageFont.FreeTypeFont, token: str, size: int) -> bytes:
    """Rasterise ``token`` to raw bytes so two glyphs can be compared exactly."""
    from PIL import Image, ImageDraw

    box = size * 2 + 8
    canvas = Image.new("RGBA", (box, box), (0, 0, 0, 0))
    ImageDraw.Draw(canvas).text((2, 2), token, font=font, embedded_color=True)
    return canvas.tobytes()


@functools.lru_cache(maxsize=64)
def load(name: str, size: int) -> ImageFont.FreeTypeFont:
    """Load and cache a sized Roboto face."""
    return ImageFont.truetype(font_file(name), int(size))
