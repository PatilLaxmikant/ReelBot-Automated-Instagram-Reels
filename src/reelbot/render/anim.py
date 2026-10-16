"""Timing and easing helpers for staggered element reveals.

Retention data is blunt about this: a static frame held longer than ~4 seconds
is where viewers scroll away, and the target is a visual change every 1.5-3
seconds. Narration scenes run 6-10 seconds, so each slide reveals its elements
in beats rather than appearing all at once.

Pillow draws onto an opaque RGB canvas, so "fade" here means interpolating a
colour toward the background rather than real alpha compositing - cheaper, and
indistinguishable at these sizes.
"""
from __future__ import annotations

import math

#: How long a single element takes to animate in.
REVEAL_DURATION = 0.42


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def ease_out_cubic(t: float) -> float:
    """Fast start, soft landing. The default for entrances."""
    return 1.0 - (1.0 - clamp(t)) ** 3


def ease_out_back(t: float) -> float:
    """Overshoots slightly then settles - reads as a 'pop'."""
    t = clamp(t)
    c1, c3 = 1.70158, 2.70158
    return 1.0 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2


def progress(scene_time: float, at: float, duration: float = REVEAL_DURATION) -> float:
    """Linear 0..1 progress of an element scheduled to appear at ``at``."""
    if scene_time < at:
        return 0.0
    if duration <= 0:
        return 1.0
    return clamp((scene_time - at) / duration)


def reveal(scene_time: float, at: float, duration: float = REVEAL_DURATION) -> float:
    """Eased 0..1 entrance progress for an element scheduled at ``at``."""
    return ease_out_cubic(progress(scene_time, at, duration))


def pop(scene_time: float, at: float, duration: float = REVEAL_DURATION) -> float:
    """Eased entrance with a slight overshoot, for hero elements."""
    return ease_out_back(progress(scene_time, at, duration))


def rise(scene_time: float, at: float, distance: int = 44, duration: float = REVEAL_DURATION) -> int:
    """Vertical offset for a slide-up entrance: ``distance`` px -> 0."""
    return int(distance * (1.0 - reveal(scene_time, at, duration)))


def lerp_colour(
    background: tuple[int, int, int],
    foreground: tuple[int, int, int],
    amount: float,
) -> tuple[int, int, int]:
    """Blend ``foreground`` toward ``background`` to fake a fade-in."""
    amount = clamp(amount)
    return tuple(  # type: ignore[return-value]
        int(background[channel] + (foreground[channel] - background[channel]) * amount)
        for channel in range(3)
    )


def breathe(scene_time: float, speed: float = 5.0, amount: int = 12) -> int:
    """A slow sine, for accent borders that should feel alive."""
    return int(math.sin(scene_time * speed) * amount)


def beats(count: int, start: float = 0.15, gap: float = 0.55) -> list[float]:
    """``count`` evenly spaced reveal times.

    The default 0.55s gap keeps something changing roughly twice a second
    during the opening of a scene.
    """
    return [start + index * gap for index in range(count)]
