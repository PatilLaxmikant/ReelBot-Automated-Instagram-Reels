"""Typed, validated runtime configuration loaded once from the environment."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv

from reelbot.store.jsonstore import read_json, write_json
from reelbot.store.paths import PROJECT_ROOT, SETTINGS_FILE

_PLACEHOLDERS = {
    "",
    "your_gemini_api_key_here",
    "your_instagram_username_here",
    "your_instagram_password_here",
}

PUBLISH_REVIEW = "review"
PUBLISH_AUTO = "auto"


def _clean(raw: str | None) -> str:
    """Normalise an env value, treating the .env.example placeholders as unset."""
    value = (raw or "").strip().strip("\"'")
    return "" if value in _PLACEHOLDERS else value


def _int(raw: str | None, fallback: int) -> int:
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return fallback


def _bool(raw: str | None, fallback: bool) -> bool:
    value = _clean(raw).lower()
    if value in ("1", "true", "yes", "on"):
        return True
    if value in ("0", "false", "no", "off"):
        return False
    return fallback


def _float(raw: str | None, fallback: float) -> float:
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError):
        return fallback


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str
    gemini_model: str
    instagram_username: str
    instagram_password: str
    tts_voice: str
    brand_handle: str
    publish_mode: str
    share_to_story: bool
    video_fps: int
    card_duration_sec: float

    @property
    def has_gemini(self) -> bool:
        return bool(self.gemini_api_key)

    @property
    def has_instagram(self) -> bool:
        return bool(self.instagram_username and self.instagram_password)

    @property
    def auto_publish(self) -> bool:
        return self.publish_mode == PUBLISH_AUTO


#: Settings the dashboard is allowed to change at runtime. Anything not listed
#: stays under .env control, so a UI bug cannot rewrite credentials.
MUTABLE = ("publish_mode", "share_to_story", "tts_voice", "brand_handle")


def _overrides() -> dict:
    """Runtime overrides written by the dashboard, layered over .env."""
    raw = read_json(SETTINGS_FILE, {})
    return {k: v for k, v in raw.items() if k in MUTABLE} if isinstance(raw, dict) else {}


def set_override(key: str, value) -> None:
    """Persist a runtime override and invalidate the cache.

    Raises:
        KeyError: if the setting is not user-changeable.
    """
    if key not in MUTABLE:
        raise KeyError(f"{key!r} is not changeable at runtime (allowed: {', '.join(MUTABLE)})")
    current = read_json(SETTINGS_FILE, {})
    if not isinstance(current, dict):
        current = {}
    current[key] = value
    write_json(SETTINGS_FILE, current)
    get_settings.cache_clear()


def clear_overrides() -> None:
    write_json(SETTINGS_FILE, {})
    get_settings.cache_clear()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load settings once per process, with dashboard overrides layered on top."""
    load_dotenv(PROJECT_ROOT / ".env")
    over = _overrides()

    mode = str(over.get("publish_mode") or _clean(os.getenv("PUBLISH_MODE"))).lower() or PUBLISH_REVIEW
    if mode not in (PUBLISH_REVIEW, PUBLISH_AUTO):
        mode = PUBLISH_REVIEW

    return Settings(
        gemini_api_key=_clean(os.getenv("GEMINI_API_KEY")),
        gemini_model=_clean(os.getenv("GEMINI_MODEL")) or "gemini-2.5-flash",
        instagram_username=_clean(os.getenv("INSTAGRAM_USERNAME")),
        instagram_password=_clean(os.getenv("INSTAGRAM_PASSWORD")),
        tts_voice=over.get("tts_voice") or _clean(os.getenv("TTS_VOICE")) or "guy",
        brand_handle=over.get("brand_handle") or _clean(os.getenv("BRAND_HANDLE")) or "@DailyEnglishTips",
        publish_mode=mode,
        share_to_story=(over["share_to_story"] if "share_to_story" in over
                        else _bool(os.getenv("SHARE_TO_STORY"), True)),
        video_fps=_int(os.getenv("VIDEO_FPS"), 24),
        card_duration_sec=_float(os.getenv("CARD_DURATION_SEC"), 10.0),
    )
