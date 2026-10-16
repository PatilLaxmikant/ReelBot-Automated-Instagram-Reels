"""End-to-end reel production.

generate_reel() is the single orchestration point: lesson -> narration ->
video -> queue entry. Both the manual CLI and the scheduled daily job call it.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from reelbot.audio.scenes import build_lesson_scenes
from reelbot.audio.tts import NarrationError, generate_narration
from reelbot.content.captions import build_caption
from reelbot.content.generator import generate_lesson
from reelbot.content.hashtags import apply_hashtags
from reelbot.formats import FORMAT_CARD, is_narrated
from reelbot.publish import queue
from reelbot.render.card import create_card_video
from reelbot.render.text import strip_emoji
from reelbot.render.thumbnail import create_thumbnail
from reelbot.render.video import create_reel_video
from reelbot.settings import get_settings
from reelbot.store import history
from reelbot.store.paths import ensure_dirs, meta_path, thumb_path

log = logging.getLogger(__name__)


class PipelineError(RuntimeError):
    """Raised when a reel could not be produced."""


@dataclass
class ReelResult:
    item: queue.QueueItem
    video_path: Path
    thumbnail_path: Path | None
    metadata_path: Path


#: Re-exported so callers keep a single import site for caption assembly.
_build_caption = build_caption


def _write_metadata(safe_name: str, lesson: dict, payload: dict) -> Path:
    path = meta_path(safe_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({**payload, "lesson_details": lesson}, handle, indent=2, ensure_ascii=False)
    return path


def generate_reel(format_key: str | None = None, voice: str | None = None) -> ReelResult:
    """Produce one complete reel and add it to the review queue.

    Raises:
        PipelineError: if generation or rendering fails.
    """
    ensure_dirs()
    settings = get_settings()
    voice = voice or settings.tts_voice

    # No history argument on purpose: the generator then loads the full account
    # memory itself, including the per-item subject keys stored with each past
    # lesson. Passing a list of titles here would silently narrow it to what a
    # headline happens to reveal.
    lesson = generate_lesson(format_key)
    resolved_format = lesson.get("format", format_key or "vocab")
    title = lesson.get("title", "English Lesson")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = f"{resolved_format}_{timestamp}"

    caption = apply_hashtags(build_caption(lesson, resolved_format), resolved_format)

    if resolved_format == FORMAT_CARD or not is_narrated(resolved_format):
        log.info("Card format - music-only pipeline (no voiceover).")
        duration = settings.card_duration_sec
        try:
            video_path, thumb = create_card_video(
                lesson, safe_name, duration=duration, fps=settings.video_fps
            )
        except Exception as exc:  # noqa: BLE001
            raise PipelineError(f"Card rendering failed: {exc}") from exc
        scene_count, total_duration = 1, duration
    else:
        scenes = build_lesson_scenes(lesson)
        if not scenes:
            raise PipelineError(f"No scenes built for format {resolved_format!r}")
        log.info("Prepared %d scenes.", len(scenes))

        try:
            narration = generate_narration(scenes, voice=voice)
        except NarrationError as exc:
            raise PipelineError(str(exc)) from exc

        thumb = create_thumbnail(lesson, thumb_path(safe_name))

        try:
            video_path = create_reel_video(narration, safe_name, fps=settings.video_fps)
        except Exception as exc:  # noqa: BLE001
            raise PipelineError(str(exc)) from exc
        finally:
            narration.audio_path.unlink(missing_ok=True)

        scene_count, total_duration = len(narration.scenes), narration.duration

    metadata = _write_metadata(
        safe_name,
        lesson,
        {
            "title": title,
            "format": resolved_format,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "video_path": str(video_path),
            "thumbnail_path": str(thumb or ""),
            "caption": caption,
            "scenes_count": scene_count,
            "total_duration_sec": total_duration,
        },
    )

    item = queue.add(
        queue.QueueItem(
            id=safe_name,
            format=resolved_format,
            title=strip_emoji(title) or title,
            caption=caption,
            video_path=str(video_path),
            thumbnail_path=str(thumb or ""),
            duration_sec=round(float(total_duration), 2),
        )
    )

    history.remember(title, lesson)
    log.info("Reel ready: %s (%.1fs)", video_path.name, total_duration)
    return ReelResult(
        item=item, video_path=video_path, thumbnail_path=thumb, metadata_path=metadata
    )
