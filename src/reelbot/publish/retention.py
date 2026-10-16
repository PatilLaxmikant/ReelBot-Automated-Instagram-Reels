"""Keep the grid to the best N posts.

Two modes, and the difference matters:

* **archive** - the post disappears from the profile grid but stays on the
  account. Views, likes and comments survive, and ``media_unarchive`` puts it
  back. This is the default.
* **delete** - permanent. The post, its view count, its comments and its saves
  are gone and cannot be recovered by anyone, including Instagram support.

Everything here is a dry run unless ``apply=True`` is passed explicitly, and
delete additionally requires ``confirm_delete=True``. Two separate gates,
because one of these modes is unrecoverable.
"""
from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from reelbot.publish.sync import PublishedPost, live_posts, load, save
from reelbot.store.jsonstore import read_json, write_json
from reelbot.store.paths import RETENTION_LOG

log = logging.getLogger(__name__)

ARCHIVE = "archive"
DELETE = "delete"
MODES = (ARCHIVE, DELETE)

#: How many posts stay on the grid.
DEFAULT_KEEP = 12

#: Never touch a post younger than this. A reel accumulates most of its reach
#: in the first days; judging it early would retire something still climbing.
MIN_AGE_DAYS = 7

#: Pause between writes, so a batch does not look like a script.
PAUSE = (6.0, 14.0)


class RetentionError(RuntimeError):
    """Raised when a retention run cannot proceed safely."""


@dataclass
class Plan:
    keep: list[PublishedPost] = field(default_factory=list)
    retire: list[PublishedPost] = field(default_factory=list)
    too_young: list[PublishedPost] = field(default_factory=list)
    mode: str = ARCHIVE

    @property
    def is_noop(self) -> bool:
        return not self.retire


@dataclass
class Outcome:
    plan: Plan
    applied: bool = False
    succeeded: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)


def _age_days(post: PublishedPost, now: datetime) -> float:
    if not post.taken_at:
        return 0.0
    try:
        taken = datetime.fromisoformat(post.taken_at)
    except ValueError:
        return 0.0
    if taken.tzinfo is None:
        taken = taken.replace(tzinfo=timezone.utc)
    return (now - taken).total_seconds() / 86400.0


def build_plan(
    keep: int = DEFAULT_KEEP,
    mode: str = ARCHIVE,
    min_age_days: float = MIN_AGE_DAYS,
    posts: list[PublishedPost] | None = None,
) -> Plan:
    """Decide which posts stay on the grid and which are retired.

    Ranked by views, then comments, then likes. Posts younger than
    ``min_age_days`` are always kept regardless of rank - they have not had
    time to earn their numbers yet.
    """
    if mode not in MODES:
        raise RetentionError(f"Unknown mode {mode!r}; expected one of {MODES}")
    if keep < 1:
        raise RetentionError("keep must be at least 1")

    now = datetime.now(timezone.utc).astimezone()
    ranked = posts if posts is not None else live_posts()

    young = [p for p in ranked if _age_days(p, now) < min_age_days]
    young_pks = {p.pk for p in young}
    eligible = [p for p in ranked if p.pk not in young_pks]

    # Young posts occupy slots but are never retired, so the number of
    # established posts kept shrinks accordingly.
    slots = max(0, keep - len(young))
    return Plan(
        keep=young + eligible[:slots],
        retire=eligible[slots:],
        too_young=young,
        mode=mode,
    )


def _record(outcome: Outcome) -> None:
    entries = read_json(RETENTION_LOG, [])
    if not isinstance(entries, list):
        entries = []
    entries.append({
        "at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "mode": outcome.plan.mode,
        "applied": outcome.applied,
        "kept": [p.pk for p in outcome.plan.keep],
        "retired": outcome.succeeded,
        "failed": [pk for pk, _ in outcome.failed],
    })
    write_json(RETENTION_LOG, entries[-200:])


def apply_plan(
    plan: Plan,
    *,
    apply: bool = False,
    confirm_delete: bool = False,
    client=None,
) -> Outcome:
    """Execute ``plan``. Does nothing unless ``apply`` is True.

    Args:
        apply: actually call Instagram. Without it this is a dry run.
        confirm_delete: required in addition to ``apply`` for DELETE mode,
            since deletion cannot be undone.

    Raises:
        RetentionError: if delete was requested without explicit confirmation.
    """
    outcome = Outcome(plan=plan)

    if plan.mode == DELETE and apply and not confirm_delete:
        raise RetentionError(
            "Refusing to delete without confirm_delete=True. Deletion is permanent "
            "and destroys view counts, comments and saves. Use mode='archive' to "
            "hide posts reversibly instead."
        )

    if not apply:
        log.info(
            "Dry run: would %s %d post(s), keep %d.",
            plan.mode, len(plan.retire), len(plan.keep),
        )
        _record(outcome)
        return outcome

    if plan.is_noop:
        log.info("Nothing to retire.")
        _record(outcome)
        return outcome

    from reelbot.publish.instagram import _client

    client = client or _client()
    known = {post.pk: post for post in load()}

    for index, post in enumerate(plan.retire):
        try:
            if plan.mode == ARCHIVE:
                client.media_archive(post.pk)
            else:
                client.media_delete(post.pk)
            outcome.succeeded.append(post.pk)

            if plan.mode == ARCHIVE and post.pk in known:
                known[post.pk].archived = True
            elif post.pk in known:
                known.pop(post.pk)

            log.info("%sd %s (%d views)", plan.mode.capitalize(), post.pk, post.play_count)
        except Exception as exc:  # noqa: BLE001 - one failure must not stop the batch
            log.warning("Could not %s %s: %s", plan.mode, post.pk, exc)
            outcome.failed.append((post.pk, str(exc)))

        if index < len(plan.retire) - 1:
            time.sleep(random.uniform(*PAUSE))

    save(list(known.values()))
    outcome.applied = True
    _record(outcome)
    return outcome


def history() -> list[dict]:
    entries = read_json(RETENTION_LOG, [])
    return entries if isinstance(entries, list) else []
