"""Mirror of what is actually live on the Instagram account.

The review queue records what this bot *published*. It cannot see posts made by
hand, posts deleted from the app, or how any of them performed afterwards. This
module pulls the account's real state so retention decisions and the dashboard
work from Instagram's numbers rather than the bot's own optimism.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from reelbot.store.jsonstore import read_json, write_json
from reelbot.store.paths import PUBLISHED_FILE

log = logging.getLogger(__name__)


@dataclass
class PublishedPost:
    """One post as Instagram reports it."""

    pk: str
    code: str = ""
    taken_at: str = ""
    caption_head: str = ""
    play_count: int = 0
    like_count: int = 0
    comment_count: int = 0
    product_type: str = ""
    archived: bool = False
    #: Queue id this came from, when the bot published it.
    queue_id: str = ""

    @property
    def url(self) -> str:
        return f"https://www.instagram.com/reel/{self.code}/" if self.code else ""

    @property
    def score(self) -> tuple[int, int, int]:
        """Ranking key: views first, then comments, then likes.

        Comments outrank likes because they are the harder signal to get and
        the one that correlates with reach on this account.
        """
        return (self.play_count, self.comment_count, self.like_count)

    @classmethod
    def from_dict(cls, raw: dict) -> "PublishedPost":
        known = {k: raw.get(k) for k in cls.__dataclass_fields__ if k in raw}
        return cls(**{k: v for k, v in known.items() if v is not None})


@dataclass
class SyncResult:
    posts: list[PublishedPost] = field(default_factory=list)
    added: int = 0
    updated: int = 0
    vanished: list[str] = field(default_factory=list)


def load() -> list[PublishedPost]:
    """Every post recorded from the account, newest first."""
    raw = read_json(PUBLISHED_FILE, {"items": []})
    items = raw.get("items", []) if isinstance(raw, dict) else []
    posts = [PublishedPost.from_dict(entry) for entry in items if isinstance(entry, dict)]
    return sorted(posts, key=lambda p: p.taken_at, reverse=True)


def save(posts: list[PublishedPost]) -> None:
    write_json(
        PUBLISHED_FILE,
        {
            "synced_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "items": [asdict(post) for post in posts],
        },
    )


def last_synced() -> str:
    raw = read_json(PUBLISHED_FILE, {})
    return raw.get("synced_at", "") if isinstance(raw, dict) else ""


def _to_post(media, queue_by_pk: dict[str, str]) -> PublishedPost:
    pk = str(getattr(media, "pk", "") or "")
    caption = str(getattr(media, "caption_text", "") or "").strip().replace("\n", " ")
    taken = getattr(media, "taken_at", None)
    return PublishedPost(
        pk=pk,
        code=str(getattr(media, "code", "") or ""),
        taken_at=taken.isoformat(timespec="seconds") if hasattr(taken, "isoformat") else "",
        caption_head=caption[:90],
        # Reels report play_count; a plain post reports neither, so fall back to 0.
        play_count=int(getattr(media, "play_count", 0) or getattr(media, "view_count", 0) or 0),
        like_count=int(getattr(media, "like_count", 0) or 0),
        comment_count=int(getattr(media, "comment_count", 0) or 0),
        product_type=str(getattr(media, "product_type", "") or ""),
        queue_id=queue_by_pk.get(pk, ""),
    )


def sync(limit: int = 60, client=None) -> SyncResult:
    """Pull the account's live posts and reconcile them with local records.

    Args:
        limit: how many recent posts to fetch (0 fetches everything).
        client: an authenticated instagrapi client; created if omitted.

    Raises:
        PublishError: if the account cannot be reached.
    """
    from reelbot.publish.instagram import PublishError, _client
    from reelbot.publish import queue

    client = client or _client()
    try:
        medias = client.user_medias(client.user_id, amount=limit)
    except Exception as exc:  # noqa: BLE001
        raise PublishError(f"Could not read the account's posts: {exc}") from exc

    queue_by_pk = {
        str(item.extra.get("ig_media_id", "")): item.id
        for item in queue.load()
        if item.extra.get("ig_media_id")
    }

    known = {post.pk: post for post in load()}
    fresh: list[PublishedPost] = []
    added = updated = 0

    for media in medias:
        post = _to_post(media, queue_by_pk)
        if not post.pk:
            continue
        previous = known.pop(post.pk, None)
        if previous is None:
            added += 1
        else:
            updated += 1
            # Keep a queue link we already knew about if this fetch lacks one.
            post.queue_id = post.queue_id or previous.queue_id
            post.archived = previous.archived
        fresh.append(post)

    # Anything we had recorded that the account no longer returns: deleted or
    # archived outside the bot. Kept, flagged, so history is not silently lost.
    vanished = []
    for pk, post in known.items():
        post.archived = True
        vanished.append(pk)
        fresh.append(post)

    save(fresh)
    log.info(
        "Synced %d posts from Instagram (%d new, %d updated, %d no longer listed).",
        len(medias), added, updated, len(vanished),
    )
    return SyncResult(posts=fresh, added=added, updated=updated, vanished=vanished)


def live_posts() -> list[PublishedPost]:
    """Posts currently visible on the profile, best-performing first."""
    return sorted(
        (post for post in load() if not post.archived),
        key=lambda p: p.score,
        reverse=True,
    )
