"""Console + rotating-file logging.

Replaces the previous ``print`` calls so that unattended Task Scheduler runs
leave an auditable trail in ``logs/reelbot.log``.
"""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from reelbot.store.paths import LOG_DIR, ensure_dirs

_CONFIGURED = False


def setup_logging(verbose: bool = False) -> None:
    """Attach handlers to the root logger. Idempotent."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    ensure_dirs()

    # Windows consoles default to cp1252, which explodes on emoji in log lines.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass

    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.DEBUG if verbose else logging.INFO)
    console.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(console)

    logfile = RotatingFileHandler(
        LOG_DIR / "reelbot.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8"
    )
    logfile.setLevel(logging.DEBUG)
    logfile.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)-28s %(message)s")
    )
    root.addHandler(logfile)

    # These libraries are extremely chatty at INFO.
    for noisy in ("urllib3", "instagrapi", "public_request", "private_request", "PIL"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _CONFIGURED = True
