"""Crash-safe JSON read/write helpers shared by every state file."""
from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def read_json(path: Path, default: Any) -> Any:
    """Return the parsed contents of ``path``, or ``default`` if unreadable."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return default
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Could not read %s (%s); falling back to default.", path.name, exc)
        return default


def write_json(path: Path, payload: Any) -> None:
    """Atomically write ``payload`` so an interrupted run cannot truncate state.

    The data is written to a temp file in the same directory and then renamed,
    which is atomic on both NTFS and POSIX filesystems.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
        os.replace(tmp_name, path)
    except BaseException:
        # Never leave a stray temp file behind if the write failed.
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
