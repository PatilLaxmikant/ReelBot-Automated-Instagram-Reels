"""Procedurally generated background music and sound effects.

Everything here is synthesised with numpy so the project ships no copyrighted
audio. Each asset is written once and reused on later runs.
"""
from __future__ import annotations

import logging
import wave
from pathlib import Path

import numpy as np

from reelbot.store.paths import BGM_DIR, SFX_DIR

log = logging.getLogger(__name__)

SAMPLE_RATE = 44_100
_MIN_VALID_BYTES = 100_000


def _write_wav(path: Path, samples: np.ndarray, peak: float = 1.0) -> Path:
    """Normalise ``samples`` to ``peak`` and write a 16-bit mono WAV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    highest = float(np.max(np.abs(samples))) or 1.0
    audio = (samples / highest * 32767 * peak).astype(np.int16)
    with wave.open(str(path), "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(audio.tobytes())
    return path


def _is_cached(path: Path) -> bool:
    return path.exists() and path.stat().st_size > _MIN_VALID_BYTES


def _timeline(duration: float) -> np.ndarray:
    return np.linspace(0, duration, int(SAMPLE_RATE * duration), False)


# --- Sound effects -------------------------------------------------------

def _make_tick() -> np.ndarray:
    t = _timeline(0.08)
    return np.sin(2 * np.pi * 1200 * t) * np.exp(-t * 90) + np.sin(2 * np.pi * 800 * t) * np.exp(-t * 70)


def _make_ding() -> np.ndarray:
    t = _timeline(1.2)
    return (
        np.sin(2 * np.pi * 1046.5 * t) * np.exp(-t * 3.5) * 0.50
        + np.sin(2 * np.pi * 2093.0 * t) * np.exp(-t * 5.0) * 0.30
        + np.sin(2 * np.pi * 3135.9 * t) * np.exp(-t * 7.0) * 0.15
        + np.sin(2 * np.pi * 4186.0 * t) * np.exp(-t * 9.0) * 0.05
    )


def _make_pop() -> np.ndarray:
    t = _timeline(0.06)
    sweep = np.linspace(300, 900, len(t))
    return np.sin(2 * np.pi * sweep * t) * np.exp(-t * 60)


def _make_whoosh() -> np.ndarray:
    t = _timeline(0.25)
    envelope = np.sin(np.pi * t / 0.25) ** 2
    return np.random.normal(0, 1, len(t)) * envelope


_SFX = {
    "tick": (_make_tick, 0.80),
    "ding": (_make_ding, 0.85),
    "pop": (_make_pop, 0.75),
    "whoosh": (_make_whoosh, 0.50),
}


def sfx_path(name: str) -> Path | None:
    """Path to a sound effect, generating it on first use."""
    if name not in _SFX:
        return None
    path = SFX_DIR / f"{name}.wav"
    if path.exists():
        return path
    build, peak = _SFX[name]
    log.debug("Generating SFX %s", name)
    return _write_wav(path, build(), peak)


def ensure_sfx() -> None:
    for name in _SFX:
        sfx_path(name)


# --- Background music ----------------------------------------------------

def _chord_stack(t_rel: np.ndarray, freqs: list[float], decays: tuple[float, float, float]) -> np.ndarray:
    """Sum a chord's fundamentals plus two harmonics, each with its own decay."""
    wave_sum = np.zeros_like(t_rel)
    for freq in freqs:
        wave_sum += (
            np.sin(2 * np.pi * freq * t_rel) * np.exp(-t_rel * decays[0])
            + np.sin(2 * np.pi * freq * 2 * t_rel) * np.exp(-t_rel * decays[1]) * 0.35
            + np.sin(2 * np.pi * freq * 3 * t_rel) * np.exp(-t_rel * decays[2]) * 0.12
        )
    return wave_sum


def ensure_lofi_bgm() -> Path:
    """A warm chill lo-fi bed that sits under the voiceover."""
    path = BGM_DIR / "chill_lofi.wav"
    if _is_cached(path):
        return path

    log.info("Generating chill lo-fi background track ...")
    duration, bpm = 60.0, 75
    t = _timeline(duration)
    beat = 60.0 / bpm
    bar = beat * 4

    chords = [
        [130.81, 196.00, 246.94, 293.66, 329.63],  # Cmaj9
        [110.00, 164.81, 220.00, 261.63, 329.63],  # Am9
        [146.83, 220.00, 261.63, 329.63, 349.23],  # Dm9
        [98.00, 146.83, 220.00, 246.94, 329.63],   # G13
    ]

    audio = np.zeros_like(t)
    bars = int(duration / bar) + 1

    for index in range(bars):
        chord = chords[index % len(chords)]
        start = index * bar
        for hit in (start, start + beat * 2.5):
            if hit >= duration:
                continue
            mask = (t >= hit) & (t < min(hit + beat * 2.8, duration))
            audio[mask] += _chord_stack(t[mask] - hit, chord, (0.9, 1.8, 3.0)) * 0.18

        root = chord[0] / 2.0
        for hit in (start, start + beat * 1.5, start + beat * 2.5):
            if hit >= duration:
                continue
            mask = (t >= hit) & (t < min(hit + beat * 1.2, duration))
            rel = t[mask] - hit
            audio[mask] += np.sin(2 * np.pi * root * rel) * np.exp(-rel * 1.2) * 0.22

    audio += np.random.normal(0, 0.008, len(t))  # tape hiss
    return _write_wav(path, np.clip(audio, -0.9, 0.9), 0.9)


def ensure_trending_beat() -> Path:
    """An upbeat pop bed for the music-only card format."""
    path = BGM_DIR / "trending_beat.wav"
    if _is_cached(path):
        return path

    log.info("Generating upbeat trending beat ...")
    duration, bpm = 30.0, 110
    t = _timeline(duration)
    beat = 60.0 / bpm
    bar = beat * 4

    chords = [
        [174.61, 220.00, 261.63, 349.23],  # Fmaj7
        [196.00, 246.94, 293.66, 392.00],  # Gmaj7
        [220.00, 261.63, 329.63, 440.00],  # Am7
        [261.63, 329.63, 392.00, 523.25],  # Cmaj7
    ]
    melody = [523.25, 587.33, 659.25, 783.99, 659.25, 523.25, 587.33, 783.99]

    audio = np.zeros_like(t)
    bars = int(duration / bar) + 1

    for index in range(bars):
        chord = chords[index % len(chords)]
        start = index * bar

        # Staccato chord stabs on every beat.
        for step in range(4):
            hit = start + step * beat
            if hit >= duration:
                continue
            mask = (t >= hit) & (t < min(hit + beat * 0.6, duration))
            audio[mask] += _chord_stack(t[mask] - hit, chord, (3.5, 5.0, 7.0)) * 0.12

        # Four-on-the-floor kick.
        for step in range(4):
            hit = start + step * beat
            if hit >= duration:
                continue
            mask = (t >= hit) & (t < min(hit + 0.15, duration))
            rel = t[mask] - hit
            sweep = np.linspace(150, 45, len(rel))
            audio[mask] += np.sin(2 * np.pi * sweep * rel) * np.exp(-rel * 25) * 0.35

        # Claps on 2 and 4.
        for step in (1, 3):
            hit = start + step * beat
            if hit >= duration:
                continue
            mask = (t >= hit) & (t < min(hit + 0.1, duration))
            rel = t[mask] - hit
            audio[mask] += np.random.normal(0, 1, len(rel)) * np.exp(-rel * 35) * 0.18
            audio[mask] += np.sin(2 * np.pi * 200 * rel) * np.exp(-rel * 40) * 0.12

        # Eighth-note hats.
        for step in range(8):
            hit = start + step * (beat / 2)
            if hit >= duration:
                continue
            mask = (t >= hit) & (t < min(hit + 0.04, duration))
            rel = t[mask] - hit
            audio[mask] += np.random.normal(0, 1, len(rel)) * np.exp(-rel * 120) * 0.08

        # Pentatonic hook.
        for step in range(4):
            hit = start + step * beat
            if hit >= duration:
                continue
            note = melody[(index * 4 + step) % len(melody)]
            mask = (t >= hit) & (t < min(hit + beat * 0.7, duration))
            rel = t[mask] - hit
            audio[mask] += np.sin(2 * np.pi * note * rel) * np.exp(-rel * 3.0) * 0.09
            audio[mask] += np.sin(2 * np.pi * note * 2 * rel) * np.exp(-rel * 5.0) * 0.03

    return _write_wav(path, np.clip(audio, -0.85, 0.85), 0.85)
