"""Local dashboard for running the bot by hand or supervising the schedule.

Binds to localhost only. It carries no authentication because it exposes the
Instagram session indirectly - it must not be put on a network interface.
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from reelbot.formats import ALL_FORMATS
from reelbot.planner import calendar
from reelbot.publish import queue, retention, sync
from reelbot.settings import MUTABLE, get_settings, set_override
from reelbot.store import history as topic_history
from reelbot.store.paths import REELS_DIR, ensure_dirs
from reelbot.web.jobs import runner

log = logging.getLogger(__name__)

STATIC = Path(__file__).parent / "static"

app = FastAPI(title="ReelBot", docs_url=None, redoc_url=None)


# --- Request bodies ------------------------------------------------------

class GenerateBody(BaseModel):
    format: str | None = None


class SettingBody(BaseModel):
    key: str
    value: str | bool


class RetentionBody(BaseModel):
    keep: int = retention.DEFAULT_KEEP
    mode: str = retention.ARCHIVE
    apply: bool = False
    confirm_delete: bool = False


# --- Page ----------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    return (STATIC / "dashboard.html").read_text(encoding="utf-8")


@app.get("/media/{name}")
def media(name: str):
    """Serve a rendered thumbnail or video, restricted to the Reels folder."""
    path = (REELS_DIR / name).resolve()
    if not path.is_file() or REELS_DIR.resolve() not in path.parents:
        raise HTTPException(404, "Not found")
    return FileResponse(path)


# --- State ---------------------------------------------------------------

@app.get("/api/state")
def state() -> dict:
    settings = get_settings()
    items = queue.load()
    live = sync.live_posts()

    return {
        "settings": {
            "publish_mode": settings.publish_mode,
            "share_to_story": settings.share_to_story,
            "tts_voice": settings.tts_voice,
            "brand_handle": settings.brand_handle,
            "has_gemini": settings.has_gemini,
            "has_instagram": settings.has_instagram,
            "mutable": list(MUTABLE),
        },
        "today": {
            "date": date.today().isoformat(),
            "format": calendar.format_for(),
            "already_ran": bool(calendar.already_ran()),
        },
        "upcoming": [
            {"date": day.isoformat(), "weekday": day.strftime("%a"), "format": fmt}
            for day, fmt in calendar.upcoming(7)
        ],
        "queue": [
            {
                "id": i.id, "format": i.format, "title": i.title, "status": i.status,
                "caption": i.caption, "duration_sec": i.duration_sec,
                "created_at": i.created_at, "error": i.error,
                "thumb": Path(i.thumbnail_path).name if i.thumbnail_path else "",
                "video": Path(i.video_path).name if i.video_path else "",
                "media_id": i.extra.get("ig_media_id", ""),
            }
            for i in reversed(items)
        ],
        "counts": {
            status: sum(1 for i in items if i.status == status)
            for status in (queue.PENDING, queue.APPROVED, queue.PUBLISHED,
                           queue.REJECTED, queue.FAILED)
        },
        "channel": {
            "live": len(live),
            "synced_at": sync.last_synced(),
            "posts": [
                {
                    "pk": p.pk, "code": p.code, "url": p.url,
                    "views": p.play_count, "likes": p.like_count,
                    "comments": p.comment_count, "taken_at": p.taken_at,
                    "caption_head": p.caption_head,
                }
                for p in live
            ],
        },
        "formats": ALL_FORMATS,
        "recent_topics": topic_history.recent(8),
        "jobs": runner.snapshot(),
    }


@app.get("/api/jobs")
def jobs() -> dict:
    return runner.snapshot()


# --- Actions -------------------------------------------------------------

def _submit(kind: str, work, label: str) -> dict:
    try:
        job = runner.submit(kind, work, label)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"job": job.id, "status": job.status}


@app.post("/api/generate")
def generate(body: GenerateBody) -> dict:
    from reelbot.pipeline import generate_reel

    fmt = body.format if body.format in ALL_FORMATS else None

    def work() -> dict:
        result = generate_reel(format_key=fmt or calendar.format_for())
        return {
            "message": f"Generated: {result.item.title}",
            "queue_id": result.item.id,
        }

    return _submit("generate", work, f"Generating {fmt or calendar.format_for()} reel")


@app.post("/api/queue/{item_id}/{action}")
def queue_action(item_id: str, action: str) -> dict:
    try:
        if action == "approve":
            item = queue.approve(item_id)
        elif action == "reject":
            item = queue.reject(item_id)
        else:
            raise HTTPException(400, f"Unknown action {action!r}")
    except queue.QueueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"id": item.id, "status": item.status}


@app.post("/api/publish")
def publish() -> dict:
    from reelbot.planner.runner import publish_approved

    ready = queue.by_status(*queue.PUBLISHABLE)
    if not ready:
        raise HTTPException(400, "Nothing approved to publish")

    def work() -> dict:
        published = publish_approved()
        return {"message": f"Published {len(published)} reel(s)",
                "published": [i.id for i in published]}

    return _submit("publish", work, f"Publishing {len(ready)} reel(s)")


@app.post("/api/sync")
def sync_channel() -> dict:
    def work() -> dict:
        result = sync.sync()
        return {"message": f"Synced {len(result.posts)} posts "
                           f"({result.added} new, {result.updated} updated)"}

    return _submit("sync", work, "Reading the account")


@app.post("/api/settings")
def update_setting(body: SettingBody) -> dict:
    value = body.value
    if body.key == "publish_mode" and value not in ("review", "auto"):
        raise HTTPException(400, "publish_mode must be 'review' or 'auto'")
    try:
        set_override(body.key, value)
    except KeyError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"key": body.key, "value": value}


@app.post("/api/retention")
def plan_retention(body: RetentionBody) -> dict:
    """Build a retention plan, and apply it only when explicitly asked."""
    try:
        plan = retention.build_plan(keep=body.keep, mode=body.mode)
    except retention.RetentionError as exc:
        raise HTTPException(400, str(exc)) from exc

    summary = {
        "mode": plan.mode,
        "keep": [{"pk": p.pk, "views": p.play_count, "caption": p.caption_head}
                 for p in plan.keep],
        "retire": [{"pk": p.pk, "views": p.play_count, "caption": p.caption_head}
                   for p in plan.retire],
        "too_young": len(plan.too_young),
    }

    if not body.apply:
        return {"applied": False, **summary}

    # Reject before submitting anything. Failing this asynchronously inside the
    # worker would return "applied: true" for a request that was never allowed.
    if plan.mode == retention.DELETE and not body.confirm_delete:
        raise HTTPException(
            400,
            "Deleting is permanent and destroys view counts, comments and saves. "
            "Send confirm_delete=true, or use mode='archive' to hide posts reversibly.",
        )
    if plan.is_noop:
        return {"applied": False, **summary, "message": "Nothing to retire"}

    def work() -> dict:
        outcome = retention.apply_plan(
            plan, apply=True, confirm_delete=body.confirm_delete
        )
        return {"message": f"{plan.mode.capitalize()}d {len(outcome.succeeded)} post(s)",
                "failed": len(outcome.failed)}

    job = _submit("retention", work, f"{plan.mode.capitalize()} {len(plan.retire)} post(s)")
    return {"applied": True, **summary, **job}


def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Run the dashboard. Localhost only - there is no authentication."""
    import uvicorn

    ensure_dirs()
    log.info("Dashboard: http://%s:%d", host, port)
    uvicorn.run(app, host=host, port=port, log_level="warning")
