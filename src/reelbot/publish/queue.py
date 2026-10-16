"""The review queue.

Generated reels land here as ``pending`` instead of going straight to
Instagram. You approve what you like, and only approved items are published.
This keeps a bad AI generation off the account and keeps posting under your
control rather than a cron job's.

State machine::

    pending --approve--> approved --publish--> published
       |                     |                     ^
       +------reject---------+                     |
       |                                           |
       +---> rejected            failed <--publish-+ (on error)
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Iterable

from reelbot.store.jsonstore import read_json, write_json
from reelbot.store.paths import QUEUE_FILE

log = logging.getLogger(__name__)

PENDING = "pending"
APPROVED = "approved"
PUBLISHED = "published"
REJECTED = "rejected"
FAILED = "failed"

#: Statuses a `publish` run will pick up.
PUBLISHABLE = (APPROVED,)
#: Statuses that still need a decision from the operator.
OPEN = (PENDING, APPROVED, FAILED)


class QueueError(RuntimeError):
    """Raised for an invalid queue operation."""


@dataclass
class QueueItem:
    id: str
    format: str
    title: str
    caption: str
    video_path: str
    thumbnail_path: str = ""
    status: str = PENDING
    created_at: str = ""
    published_at: str | None = None
    error: str | None = None
    duration_sec: float = 0.0
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict) -> "QueueItem":
        known = {key: raw.get(key) for key in cls.__dataclass_fields__ if key in raw}
        known.setdefault("id", raw.get("id", ""))
        known["extra"] = raw.get("extra") or {}
        return cls(**{k: v for k, v in known.items() if v is not None})


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def load() -> list[QueueItem]:
    """Every queue item, oldest first."""
    raw = read_json(QUEUE_FILE, {"items": []})
    items = raw.get("items", []) if isinstance(raw, dict) else []
    return [QueueItem.from_dict(entry) for entry in items if isinstance(entry, dict)]


def save(items: Iterable[QueueItem]) -> None:
    write_json(QUEUE_FILE, {"items": [asdict(item) for item in items]})


def add(item: QueueItem) -> QueueItem:
    """Append a freshly generated item as ``pending``."""
    item.created_at = item.created_at or _now()
    item.status = item.status or PENDING
    items = load()
    items.append(item)
    save(items)
    log.info("Queued for review: %s (%s)", item.title, item.id)
    return item


def find(item_id: str) -> QueueItem | None:
    for item in load():
        if item.id == item_id:
            return item
    return None


def by_status(*statuses: str) -> list[QueueItem]:
    wanted = set(statuses)
    return [item for item in load() if item.status in wanted]


def update(item_id: str, **changes) -> QueueItem:
    """Apply ``changes`` to one item and persist. Raises if it does not exist."""
    items = load()
    for item in items:
        if item.id == item_id:
            for key, value in changes.items():
                setattr(item, key, value)
            save(items)
            return item
    raise QueueError(f"No queue item with id {item_id!r}")


def set_status(item_id: str, status: str, error: str | None = None) -> QueueItem:
    changes: dict = {"status": status, "error": error}
    if status == PUBLISHED:
        changes["published_at"] = _now()
    return update(item_id, **changes)


def approve(item_id: str) -> QueueItem:
    item = find(item_id)
    if item is None:
        raise QueueError(f"No queue item with id {item_id!r}")
    if item.status == PUBLISHED:
        raise QueueError(f"{item_id} is already published")
    return set_status(item_id, APPROVED)


def reject(item_id: str) -> QueueItem:
    item = find(item_id)
    if item is None:
        raise QueueError(f"No queue item with id {item_id!r}")
    if item.status == PUBLISHED:
        raise QueueError(f"{item_id} is already published; nothing to reject")
    return set_status(item_id, REJECTED)


def approve_all() -> list[QueueItem]:
    """Approve every pending item. Returns the items that changed."""
    changed = []
    items = load()
    for item in items:
        if item.status == PENDING:
            item.status = APPROVED
            changed.append(item)
    if changed:
        save(items)
    return changed


def prune(keep_published: int = 50) -> int:
    """Drop old published/rejected entries. Returns how many were removed."""
    items = load()
    finished = [i for i in items if i.status in (PUBLISHED, REJECTED)]
    if len(finished) <= keep_published:
        return 0
    drop = {id(i) for i in finished[: len(finished) - keep_published]}
    kept = [i for i in items if id(i) not in drop]
    save(kept)
    return len(items) - len(kept)
