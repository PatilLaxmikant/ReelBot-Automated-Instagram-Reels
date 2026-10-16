"""Central filesystem layout.

Every path is anchored to the project root rather than the working directory,
so the bot behaves identically when launched by Task Scheduler (which sets an
arbitrary CWD) and when launched by hand.
"""
from __future__ import annotations

from pathlib import Path

# src/reelbot/store/paths.py -> store -> reelbot -> src -> PROJECT_ROOT
PROJECT_ROOT = Path(__file__).resolve().parents[3]

DATA_DIR = PROJECT_ROOT / "data"
LOG_DIR = PROJECT_ROOT / "logs"
REELS_DIR = PROJECT_ROOT / "Reels"
ASSETS_DIR = PROJECT_ROOT / "assets"
BGM_DIR = ASSETS_DIR / "bgm"
SFX_DIR = ASSETS_DIR / "sfx"
FONT_DIR = ASSETS_DIR / "fonts"

# State files
HISTORY_FILE = DATA_DIR / "lesson_history.json"
CALENDAR_FILE = DATA_DIR / "calendar_log.json"
HASHTAG_FILE = DATA_DIR / "hashtag_history.json"
QUEUE_FILE = DATA_DIR / "queue.json"
PUBLISHED_FILE = DATA_DIR / "published.json"
RETENTION_LOG = DATA_DIR / "retention_log.json"
SCHEDULE_FILE = DATA_DIR / "schedule.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
IG_SESSION_FILE = DATA_DIR / "ig_session.json"

_WRITABLE = (DATA_DIR, LOG_DIR, REELS_DIR, BGM_DIR, SFX_DIR, FONT_DIR)


def ensure_dirs() -> None:
    """Create every directory the bot writes into. Safe to call repeatedly."""
    for directory in _WRITABLE:
        directory.mkdir(parents=True, exist_ok=True)


def reel_path(safe_name: str) -> Path:
    return REELS_DIR / f"reel_{safe_name}.mp4"


def thumb_path(safe_name: str) -> Path:
    return REELS_DIR / f"thumb_{safe_name}.jpg"


def meta_path(safe_name: str) -> Path:
    return REELS_DIR / f"meta_{safe_name}.json"
