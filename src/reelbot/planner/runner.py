"""The daily scheduled job.

This is what Windows Task Scheduler invokes. It is deliberately idempotent:
Task Scheduler re-fires missed tasks when the machine wakes, and generating two
reels for the same date would burn API quota and clutter the queue.
"""
from __future__ import annotations

import logging
import random
import time
from datetime import date

from reelbot.planner import calendar
from reelbot.pipeline import PipelineError, ReelResult, generate_reel
from reelbot.publish import queue
from reelbot.settings import get_settings

log = logging.getLogger(__name__)


def run_daily(force: bool = False, day: date | None = None) -> ReelResult | None:
    """Generate today's scheduled reel.

    Args:
        force: generate even if a reel was already made for this date.
        day: override the date used to pick the format (for testing).

    Returns:
        The produced reel, or None if today's reel already existed.
    """
    day = day or date.today()

    existing = calendar.already_ran(day)
    if existing and not force:
        log.info(
            "A reel was already generated for %s (%s / %s). Use --force to make another.",
            day.isoformat(), existing.get("format"), existing.get("title"),
        )
        return None

    format_key = calendar.format_for(day)
    log.info("Scheduled format for %s: %s", day.strftime("%A %d %b %Y"), format_key.upper())

    _refresh_account_memory()

    try:
        result = generate_reel(format_key=format_key)
    except PipelineError:
        log.exception("Daily run failed for %s", day.isoformat())
        raise

    calendar.record_run(day, format_key, result.item.title, result.item.id)

    settings = get_settings()
    if settings.auto_publish:
        log.info("PUBLISH_MODE=auto - publishing immediately.")
        publish_approved(auto_approve_id=result.item.id)
    else:
        log.info(
            "Held for review. Approve with:  reelbot queue approve %s", result.item.id
        )

    return result


def _refresh_account_memory() -> bool:
    """Pull the account's live posts so the topic memory is current.

    The bot's own posts are already remembered through the queue. This exists
    for the ones it cannot see: anything posted by hand from the phone. Without
    it the memory is only as fresh as the last manual ``reelbot sync``, and the
    generator will happily re-teach a topic posted last week.

    Best-effort and read-only. A daily run must not fail because Instagram was
    unreachable, so this returns False rather than raising.
    """
    if not get_settings().has_instagram:
        log.debug("No Instagram credentials; skipping the account refresh.")
        return False

    from reelbot.publish import sync

    try:
        result = sync.sync()
        log.info("Account memory refreshed: %d live posts.", len(result.posts))
        return True
    except Exception as exc:  # noqa: BLE001 - never block generation on a read
        log.warning(
            "Could not refresh the account memory (%s). Falling back to the last "
            "sync, so a topic posted by hand since then may repeat.", exc,
        )
        return False


def publish_approved(auto_approve_id: str | None = None) -> list[queue.QueueItem]:
    """Upload every approved queue item. Returns the items that published."""
    from reelbot.publish.instagram import PublishError, upload_reel

    if auto_approve_id:
        queue.approve(auto_approve_id)

    ready = queue.by_status(*queue.PUBLISHABLE)
    if not ready:
        log.info("Nothing approved to publish.")
        return []

    published: list[queue.QueueItem] = []
    for item in ready:
        try:
            media_id = upload_reel(
                item.video_path, item.caption, item.thumbnail_path or None
            )
            item.extra["ig_media_id"] = media_id
            story_id = _reshare_to_story(item, media_id)
            if story_id:
                item.extra["ig_story_id"] = story_id
            queue.update(item.id, extra=item.extra)
            queue.set_status(item.id, queue.PUBLISHED)
            published.append(item)
        except PublishError as exc:
            log.error("Publish failed for %s: %s", item.id, exc)
            queue.set_status(item.id, queue.FAILED, error=str(exc))

    return published


def _reshare_to_story(item: queue.QueueItem, media_id: str) -> str | None:
    """Put the just-published reel on the account's story.

    Deliberately best-effort. The reel is already live at this point, so a story
    failure is logged and ignored rather than failing the publish.
    """
    if not get_settings().share_to_story or not media_id:
        return None

    from reelbot.publish.instagram import share_to_story
    from reelbot.render.story import create_story_background, story_path

    try:
        # The format drives the badge, accent and tap prompt, so the story
        # actually reads as belonging to this reel rather than being a generic
        # card identical for every post.
        lesson = {"title": item.title, "format": item.format}
        background = create_story_background(lesson, story_path(item.id))
        # A short pause between two writes looks less scripted than firing
        # them back to back.
        time.sleep(random.uniform(4, 9))
        return share_to_story(media_id, background)
    except Exception as exc:  # noqa: BLE001 - never fail a published reel
        log.warning("Story reshare skipped for %s: %s", item.id, exc)
        return None
