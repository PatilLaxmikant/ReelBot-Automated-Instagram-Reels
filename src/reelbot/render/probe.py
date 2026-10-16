"""Optional draw recorder, used by the layout tests.

Pixel tests can prove nothing was drawn in a forbidden *band* of the frame, but
they cannot tell whether a line of text overflowed the panel it belongs to -
which is exactly how the recap rows shipped with headings spilling out of their
boxes while the suite stayed green.

This records the geometry as it is drawn so a test can assert containment
directly. It is inert unless a recorder is active, so production renders pay
only a module-level ``None`` check per draw call.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field

Box = tuple[float, float, float, float]

_active: "Recorder | None" = None


@dataclass
class Recorder:
    """Panels and text boxes captured during one slide render."""

    panels: list[Box] = field(default_factory=list)
    texts: list[tuple[Box, str]] = field(default_factory=list)

    def owner_of(self, box: Box) -> Box | None:
        """The smallest recorded panel whose bounds contain ``box``'s origin.

        Text whose origin sits on bare background (a slide title, say) has no
        owner and is not subject to containment.
        """
        left, top = box[0], box[1]
        owners = [
            panel for panel in self.panels
            if panel[0] <= left <= panel[2] and panel[1] <= top <= panel[3]
        ]
        if not owners:
            return None
        return min(owners, key=lambda p: (p[2] - p[0]) * (p[3] - p[1]))

    def overflows(self, tolerance: float = 4.0) -> list[tuple[str, Box, Box]]:
        """Every ``(text, text_box, panel_box)`` that escapes its own panel."""
        escaped = []
        for box, content in self.texts:
            panel = self.owner_of(box)
            if panel is None:
                continue
            if (
                box[0] < panel[0] - tolerance
                or box[1] < panel[1] - tolerance
                or box[2] > panel[2] + tolerance
                or box[3] > panel[3] + tolerance
            ):
                escaped.append((content, box, panel))
        return escaped


@contextmanager
def recording():
    """Capture draw geometry for the duration of the block."""
    global _active
    previous, _active = _active, Recorder()
    try:
        yield _active
    finally:
        _active = previous


def note_panel(box: Box) -> None:
    if _active is not None:
        _active.panels.append((float(box[0]), float(box[1]), float(box[2]), float(box[3])))


def note_text(box: Box, content: str) -> None:
    if _active is not None:
        _active.texts.append(
            ((float(box[0]), float(box[1]), float(box[2]), float(box[3])), content)
        )


def is_recording() -> bool:
    return _active is not None
