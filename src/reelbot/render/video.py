"""The narrated multi-scene reel compositor.

Two things differ from the original implementation:

* ``CompositeAudioClip`` is imported. It was used but never imported, so every
  narrated format raised ``NameError`` and produced no video at all.
* Frames are generated on demand through ``VideoClip`` instead of being
  accumulated in a list. A 48-second reel is ~1,150 frames of 1080x1920x3,
  which held roughly 7 GB of numpy arrays in memory at once.
"""
from __future__ import annotations

import bisect
import logging
import math
from pathlib import Path

import numpy as np
from moviepy.audio.fx import all as afx
from moviepy.editor import AudioFileClip, CompositeAudioClip, VideoClip, concatenate_audioclips
from PIL import ImageDraw

from reelbot.audio.assets import ensure_lofi_bgm, sfx_path
from reelbot.audio.tts import Narration
from reelbot.render.components import draw_progress, draw_subtitles, new_frame
from reelbot.render.slides import render_slide
from reelbot.render.theme import reel_fonts
from reelbot.store.paths import reel_path

log = logging.getLogger(__name__)

BGM_VOLUME = 0.13
POP_VOLUME = 0.35
TICK_VOLUME = 0.85
DING_VOLUME = 0.70

#: Scene types that get a transition pop when they start.
_POP_SCENES = {"vocab_item", "native_item", "corporate_item", "mistake_word"}


class SceneTimeline:
    """Maps a playback time onto the scene that owns it."""

    def __init__(self, scenes: list[dict]) -> None:
        self._scenes = scenes or [{}]
        self._starts = [float(scene.get("start", 0.0)) for scene in self._scenes]

    def at(self, time: float) -> tuple[dict, float]:
        """Return ``(scene, time_within_scene)`` for playback time ``time``."""
        index = bisect.bisect_right(self._starts, time) - 1
        index = max(0, min(index, len(self._scenes) - 1))
        scene = self._scenes[index]
        return scene, max(0.0, time - float(scene.get("start", 0.0)))


def _bgm_layer(duration: float) -> AudioFileClip | None:
    """A looped, faded lo-fi bed sitting under the voice."""
    try:
        path = ensure_lofi_bgm()
        clip = AudioFileClip(str(path))
        if clip.duration < duration:
            clip = concatenate_audioclips([clip] * (math.ceil(duration / clip.duration) + 1))
        clip = clip.subclip(0, duration).volumex(BGM_VOLUME)
        clip = afx.audio_fadein(clip, min(1.0, duration * 0.1))
        return afx.audio_fadeout(clip, min(1.5, duration * 0.15))
    except Exception as exc:  # noqa: BLE001 - music is optional garnish
        log.warning("Could not mix background music: %s", exc)
        return None


def _sfx_layers(scenes: list[dict]) -> list[AudioFileClip]:
    """Countdown ticks, the reveal chime, and per-item transition pops."""
    layers: list[AudioFileClip] = []

    for scene in scenes:
        kind = scene.get("type", "")
        start = float(scene.get("start", 0.0))

        try:
            if kind == "quiz_countdown":
                tick = sfx_path("tick")
                if tick:
                    for offset in (0.05, 1.05, 2.05):
                        layers.append(
                            AudioFileClip(str(tick)).volumex(TICK_VOLUME).set_start(start + offset)
                        )
            elif kind == "quiz_reveal":
                ding = sfx_path("ding")
                if ding:
                    layers.append(
                        AudioFileClip(str(ding)).volumex(DING_VOLUME).set_start(start + 0.05)
                    )
            elif kind in _POP_SCENES:
                pop = sfx_path("pop") or sfx_path("whoosh")
                if pop:
                    layers.append(AudioFileClip(str(pop)).volumex(POP_VOLUME).set_start(start))
        except Exception as exc:  # noqa: BLE001 - one bad SFX must not kill the render
            log.debug("Skipped SFX for %s: %s", kind, exc)

    return layers


def create_reel_video(narration: Narration, safe_name: str, fps: int) -> Path:
    """Render the narrated reel and return its path.

    Raises:
        RuntimeError: if the video could not be written.
    """
    fonts = reel_fonts()
    timeline = SceneTimeline(narration.scenes)
    duration = narration.duration
    log.info("Rendering reel: %d scenes, %.1fs, %d fps ...", len(narration.scenes), duration, fps)

    def make_frame(time: float) -> np.ndarray:
        """Render exactly one frame. Pure function of ``time``."""
        index = int(time * fps)
        image = new_frame(index)
        draw = ImageDraw.Draw(image)

        scene, scene_time = timeline.at(time)
        render_slide(draw, scene, scene_time, fonts)
        draw_subtitles(draw, time, narration.cues, fonts)
        draw_progress(draw, time / duration if duration else 0.0)

        return np.asarray(image)

    voice = None
    master = None
    video = None
    final = None
    extra: list[AudioFileClip] = []

    try:
        voice = AudioFileClip(str(narration.audio_path))
        layers: list[AudioFileClip] = [voice]

        bgm = _bgm_layer(duration)
        if bgm is not None:
            extra.append(bgm)
            layers.append(bgm)

        sfx = _sfx_layers(narration.scenes)
        extra.extend(sfx)
        layers.extend(sfx)

        master = CompositeAudioClip(layers).set_duration(duration)
        video = VideoClip(make_frame, duration=duration)
        final = video.set_audio(master)

        out = reel_path(safe_name)
        out.parent.mkdir(parents=True, exist_ok=True)
        final.write_videofile(
            str(out),
            fps=fps,
            codec="libx264",
            audio_codec="aac",
            bitrate="8000k",
            ffmpeg_params=["-crf", "18", "-pix_fmt", "yuv420p"],
            preset="fast",
            logger=None,
        )
        log.info("Reel created: %s", out)
        return out

    except Exception as exc:  # noqa: BLE001 - surface as one typed failure
        raise RuntimeError(f"Reel rendering failed: {exc}") from exc

    finally:
        for clip in [final, video, master, voice, *extra]:
            try:
                if clip is not None:
                    clip.close()
            except Exception:  # noqa: BLE001
                pass
