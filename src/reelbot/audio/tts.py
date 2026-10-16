"""Edge-TTS narration.

Each scene is synthesised separately so its exact duration is known before the
video is rendered; the clips are then concatenated into one master track and
the per-word subtitle cues are shifted onto that master timeline.
"""
from __future__ import annotations

import asyncio
import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path

import edge_tts
from moviepy.editor import AudioFileClip, concatenate_audioclips

log = logging.getLogger(__name__)

DEFAULT_VOICE = "en-US-GuyNeural"

#: Friendly aliases for the expressive neural voices that suit this content.
VOICE_ALIASES = {
    "guy": "en-US-GuyNeural",
    "jenny": "en-US-JennyNeural",
    "brian": "en-US-BrianNeural",
    "aria": "en-US-AriaNeural",
    "emma": "en-US-EmmaNeural",
    "eric": "en-US-EricNeural",
    "ryan": "en-GB-RyanNeural",
    "sonia": "en-GB-SoniaNeural",
}

VOICE_DESCRIPTIONS = {
    "guy": "Conversational, warm American male (default)",
    "jenny": "Friendly, clear American female",
    "brian": "Deep, calm American male",
    "aria": "Bright, energetic American female",
    "emma": "Natural, conversational American female",
    "eric": "Confident, articulate American male",
    "ryan": "Crisp, articulate British male",
    "sonia": "Warm, sophisticated British female",
}


class NarrationError(RuntimeError):
    """Raised when narration could not be synthesised."""


@dataclass
class Narration:
    """The synthesised master track plus everything needed to render against it."""

    audio_path: Path
    scenes: list[dict]      # input scenes annotated with start/end/duration
    cues: list[dict]        # word-level subtitle cues on the master timeline
    duration: float


def resolve_voice(name: str | None) -> str:
    """Map an alias like ``guy`` to a full Edge-TTS voice id."""
    if not name:
        return DEFAULT_VOICE
    return VOICE_ALIASES.get(name.lower().strip(), name.strip())


def _seconds(value) -> float:
    """Coerce a timedelta / HH:MM:SS string / number into seconds."""
    if hasattr(value, "total_seconds"):
        return value.total_seconds()
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        parts = value.split(":")
        try:
            if len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
            if len(parts) == 2:
                return int(parts[0]) * 60 + float(parts[1])
        except ValueError:
            return 0.0
    return 0.0


async def _synthesize(text: str, voice: str, out_path: Path) -> list[dict]:
    """Render one scene to ``out_path`` and return its word-boundary cues."""
    communicate = edge_tts.Communicate(text, voice=voice)
    submaker = edge_tts.SubMaker()

    with open(out_path, "wb") as handle:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                handle.write(chunk["data"])
            elif chunk["type"] in ("WordBoundary", "SentenceBoundary"):
                submaker.feed(chunk)

    return [
        {
            "start": _seconds(cue.start),
            "end": _seconds(cue.end),
            "text": cue.content.strip(),
        }
        for cue in (submaker.cues or [])
    ]


async def _synthesize_with_fallback(text: str, voice: str, out_path: Path) -> list[dict]:
    try:
        return await _synthesize(text, voice, out_path)
    except Exception as exc:  # noqa: BLE001 - any edge-tts failure should retry once
        if voice == DEFAULT_VOICE:
            raise
        log.warning("Voice %s failed (%s); retrying with %s.", voice, exc, DEFAULT_VOICE)
        return await _synthesize(text, DEFAULT_VOICE, out_path)


async def _synthesize_all(scenes: list[dict], voice: str, workdir: Path) -> list[tuple[Path, list[dict]]]:
    """Synthesise every scene concurrently; edge-tts is network-bound."""
    paths = [workdir / f"scene_{idx:03d}.mp3" for idx in range(len(scenes))]
    results = await asyncio.gather(
        *(
            _synthesize_with_fallback(scene["text"], voice, path)
            for scene, path in zip(scenes, paths)
        )
    )
    return list(zip(paths, results))


def generate_narration(
    scenes: list[dict], voice: str = DEFAULT_VOICE, output: Path | None = None
) -> Narration:
    """Synthesise ``scenes`` into one master track with an aligned timeline.

    Raises:
        NarrationError: if synthesis or concatenation fails.
    """
    if not scenes:
        raise NarrationError("No scenes to narrate")

    resolved = resolve_voice(voice)
    log.info("Synthesising narration (%s) across %d scenes ...", resolved, len(scenes))

    tmpdir = Path(tempfile.mkdtemp(prefix="reelbot_tts_"))
    master = Path(output) if output else tmpdir / "master_voice.mp3"
    clips: list[AudioFileClip] = []

    try:
        rendered = asyncio.run(_synthesize_all(scenes, resolved, tmpdir))

        timeline = 0.0
        timed_scenes: list[dict] = []
        cues: list[dict] = []

        for scene, (path, raw_cues) in zip(scenes, rendered):
            clip = AudioFileClip(str(path))
            clips.append(clip)

            cues.extend(
                {
                    "start": timeline + cue["start"],
                    "end": timeline + cue["end"],
                    "text": cue["text"],
                }
                for cue in raw_cues
            )

            timed = dict(scene)
            timed["start"] = timeline
            timed["end"] = timeline + clip.duration
            timed["duration"] = clip.duration
            timed_scenes.append(timed)
            timeline += clip.duration

        master.parent.mkdir(parents=True, exist_ok=True)
        combined = concatenate_audioclips(clips)
        try:
            combined.write_audiofile(str(master), logger=None)
            total = combined.duration
        finally:
            combined.close()

        log.info("Narration ready: %.2fs across %d scenes.", total, len(timed_scenes))
        return Narration(audio_path=master, scenes=timed_scenes, cues=cues, duration=total)

    except Exception as exc:  # noqa: BLE001 - surface as one typed failure
        raise NarrationError(f"Narration failed: {exc}") from exc
    finally:
        for clip in clips:
            try:
                clip.close()
            except Exception:  # noqa: BLE001
                pass
        for leftover in tmpdir.glob("scene_*.mp3"):
            leftover.unlink(missing_ok=True)
        if master.parent != tmpdir:
            try:
                tmpdir.rmdir()
            except OSError:
                pass
