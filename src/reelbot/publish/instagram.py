"""Instagram upload via instagrapi.

Session handling matters more than it looks: a full username/password login on
every run is what trips Instagram's automation checks. The saved session is
validated with a cheap authenticated call first, and a password login only
happens when that session is genuinely dead.
"""
from __future__ import annotations

import logging
from pathlib import Path

from reelbot.settings import get_settings
from reelbot.store.paths import IG_SESSION_FILE

log = logging.getLogger(__name__)


class PublishError(RuntimeError):
    """Raised when a reel could not be published."""


def _silence_expose(client) -> None:
    """Stop a dead telemetry endpoint from failing a successful upload.

    instagrapi ends every upload with ``self.expose()``, an A/B-testing ping to
    ``/api/v1/qe/expose/``. Instagram removed that endpoint, so it now returns
    404 and instagrapi raises - *after* the media has been configured::

        if configured:
            media = self.last_json.get("media")
            self.expose()                     # <- raises here
            return extract_media_v1(media)    # <- never reached

    The reel goes live, the caller sees an exception, and the queue records a
    failure for a post that exists. Re-running then publishes it twice.

    ``expose`` returns nothing anyone reads, so it is replaced with a no-op on
    our own client instance rather than patched globally.
    """
    try:
        client.expose = lambda *_a, **_k: {}
    except Exception as exc:  # noqa: BLE001 - a future instagrapi may seal this
        log.debug("Could not neutralise expose(): %s", exc)


def _client():
    """An authenticated instagrapi client, reusing the stored session if valid."""
    from instagrapi import Client

    settings = get_settings()
    if not settings.has_instagram:
        raise PublishError("INSTAGRAM_USERNAME / INSTAGRAM_PASSWORD are not set in .env")

    client = Client()
    client.delay_range = [2, 5]  # behave less like a bot between requests
    _silence_expose(client)

    if IG_SESSION_FILE.exists():
        try:
            client.load_settings(IG_SESSION_FILE)
            client.get_timeline_feed()  # cheap authenticated probe
            log.info("Reusing saved Instagram session.")
            return client
        except Exception as exc:  # noqa: BLE001 - any failure means re-login
            log.info("Saved session unusable (%s); logging in fresh.", exc)
            client = Client()
            client.delay_range = [2, 5]
            _silence_expose(client)

    log.info("Logging into Instagram as %s ...", settings.instagram_username)
    try:
        client.login(settings.instagram_username, settings.instagram_password)
    except Exception as exc:  # noqa: BLE001
        raise PublishError(f"Instagram login failed: {exc}") from exc

    IG_SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    client.dump_settings(IG_SESSION_FILE)
    return client


#: How far back to look when checking whether a failed upload actually landed.
#: Long enough to cover a slow transcode, short enough not to match yesterday.
RECONCILE_WINDOW_MINUTES = 20

#: How much of a caption identifies it. The whole caption round-trips through
#: Instagram unchanged, but the head is enough and is cheap to compare.
_CAPTION_KEY_CHARS = 80


def _caption_key(caption: str) -> str:
    return " ".join(str(caption or "").split())[:_CAPTION_KEY_CHARS].casefold()


def _find_just_published(client, caption: str, within: int = RECONCILE_WINDOW_MINUTES) -> str:
    """Media id of a post matching ``caption`` that went live in the last ``within`` minutes.

    Returns ``""`` when nothing matches, including when the account cannot be
    read - a failed lookup must not turn into a claim that the reel published.
    """
    from datetime import datetime, timedelta, timezone

    wanted = _caption_key(caption)
    if not wanted:
        return ""

    try:
        medias = client.user_medias(client.user_id, amount=3)
    except Exception as exc:  # noqa: BLE001 - we are already in a failure path
        log.debug("Could not check whether the upload landed: %s", exc)
        return ""

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=within)
    for media in medias:
        taken = getattr(media, "taken_at", None)
        if hasattr(taken, "tzinfo"):
            moment = taken if taken.tzinfo else taken.replace(tzinfo=timezone.utc)
            if moment < cutoff:
                continue
        if _caption_key(getattr(media, "caption_text", "")) == wanted:
            return str(getattr(media, "pk", "") or getattr(media, "id", ""))
    return ""


def upload_reel(video_path: Path, caption: str, thumbnail_path: Path | None = None) -> str:
    """Upload one reel and return its Instagram media id.

    Raises:
        PublishError: on any login or upload failure.
    """
    video = Path(video_path)
    if not video.exists():
        raise PublishError(f"Video not found: {video}")

    client = _client()
    log.info("Uploading %s to Instagram ...", video.name)

    kwargs = {}
    if thumbnail_path and Path(thumbnail_path).exists():
        kwargs["thumbnail"] = Path(thumbnail_path)

    try:
        media = client.clip_upload(video, caption, **kwargs)
    except Exception as exc:  # noqa: BLE001
        # An upload can raise after the media is already live - instagrapi's
        # trailing expose() call did exactly that. Ask the account before
        # reporting a failure, or the retry posts the same reel twice.
        landed = _find_just_published(client, caption)
        if landed:
            log.warning(
                "Upload raised (%s) but the reel is live as %s; treating it as published.",
                exc, landed,
            )
            return landed
        raise PublishError(f"Upload failed: {exc}") from exc

    media_id = str(getattr(media, "pk", "") or getattr(media, "id", ""))
    log.info("Reel published. Media id: %s", media_id)
    return media_id


def share_to_story(media_pk: str, background_path: Path, client=None) -> str | None:
    """Reshare a published reel to Stories as a tappable preview.

    Returns the story's id, or None if it could not be posted.

    This never raises: the reel is already live by the time this runs, and a
    failed story must not mark a successful post as failed.
    """
    from instagrapi.types import StoryMedia

    background = Path(background_path)
    if not background.exists():
        log.warning("Story backdrop missing (%s); skipping the story.", background)
        return None

    from reelbot.render.story import STICKER

    try:
        client = client or _client()
        # Placement is explicit rather than instagrapi's centred default: the
        # backdrop needs room above the preview for the reel's own headline,
        # so the sticker sits lower and slightly narrower.
        story = client.photo_upload_to_story(
            background,
            medias=[StoryMedia(
                media_pk=int(media_pk),
                x=STICKER.x, y=STICKER.y,
                width=STICKER.width, height=STICKER.height,
            )],
        )
    except Exception as exc:  # noqa: BLE001 - the reel is already published
        log.warning("Could not share to story: %s", exc)
        return None

    story_id = str(getattr(story, "pk", "") or getattr(story, "id", ""))
    log.info("Reel reshared to story. Story id: %s", story_id)
    return story_id
