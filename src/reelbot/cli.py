"""Command line interface.

    reelbot run-daily            generate today's scheduled reel (Task Scheduler)
    reelbot generate --format X  generate one reel now
    reelbot queue list           show what is awaiting review
    reelbot queue approve <id>   approve one item (or 'all')
    reelbot queue reject <id>    reject one item
    reelbot publish              upload everything approved
    reelbot schedule             show the weekly rotation
    reelbot doctor               check the install
    reelbot voices               list narration voices
"""
from __future__ import annotations

import argparse
import logging
import sys

from reelbot.formats import ALL_FORMATS
from reelbot.logging_setup import setup_logging

log = logging.getLogger("reelbot")

_STATUS_MARK = {
    "pending": "[ ]",
    "approved": "[+]",
    "published": "[*]",
    "rejected": "[x]",
    "failed": "[!]",
}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="reelbot",
        description="Automated English-learning Instagram Reels generator.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate = subparsers.add_parser("generate", help="generate one reel now")
    generate.add_argument("--format", choices=ALL_FORMATS, default=None,
                          help="content format (default: today's scheduled format)")
    generate.add_argument("--voice", default=None, help="narration voice or alias")
    generate.add_argument("--publish", action="store_true",
                          help="approve and upload immediately, skipping review")

    daily = subparsers.add_parser("run-daily", help="generate today's scheduled reel")
    daily.add_argument("--force", action="store_true",
                       help="generate even if today's reel already exists")

    queue_parser = subparsers.add_parser("queue", help="inspect and manage the review queue")
    queue_sub = queue_parser.add_subparsers(dest="queue_command", required=True)
    queue_sub.add_parser("list", help="show queue contents")
    approve = queue_sub.add_parser("approve", help="approve an item")
    approve.add_argument("id", help="queue id, or 'all' for every pending item")
    reject = queue_sub.add_parser("reject", help="reject an item")
    reject.add_argument("id")
    queue_sub.add_parser("prune", help="drop old published/rejected entries")

    subparsers.add_parser("publish", help="upload every approved item")

    schedule = subparsers.add_parser("schedule", help="show the weekly rotation")
    schedule.add_argument("--days", type=int, default=7, help="how many days to preview")

    web = subparsers.add_parser("web", help="open the dashboard")
    web.add_argument("--host", default="127.0.0.1", help="bind address (localhost only by default)")
    web.add_argument("--port", type=int, default=8000)

    sync_p = subparsers.add_parser("sync", help="read the account's live posts")
    sync_p.add_argument("--limit", type=int, default=60, help="how many recent posts to fetch")

    prune = subparsers.add_parser("prune-channel", help="keep only the best N posts on the grid")
    prune.add_argument("--keep", type=int, default=12)
    prune.add_argument("--mode", choices=("archive", "delete"), default="archive",
                       help="archive hides reversibly; delete is permanent")
    prune.add_argument("--apply", action="store_true", help="actually do it (default: dry run)")
    prune.add_argument("--yes-delete-permanently", action="store_true",
                       help="required with --mode delete --apply")

    subparsers.add_parser("doctor", help="check configuration and dependencies")
    subparsers.add_parser("voices", help="list available narration voices")
    return parser


# --- Commands ------------------------------------------------------------

def _cmd_generate(args) -> int:
    from reelbot.pipeline import PipelineError, generate_reel
    from reelbot.planner import calendar
    from reelbot.planner.runner import publish_approved

    format_key = args.format or calendar.format_for()
    try:
        result = generate_reel(format_key=format_key, voice=args.voice)
    except PipelineError as exc:
        log.error("Generation failed: %s", exc)
        return 1

    print(f"\nReel ready: {result.video_path}")
    print(f"Queue id:   {result.item.id}")

    if args.publish:
        published = publish_approved(auto_approve_id=result.item.id)
        return 0 if published else 1

    print(f"\nReview it, then:  reelbot queue approve {result.item.id}")
    return 0


def _cmd_run_daily(args) -> int:
    from reelbot.pipeline import PipelineError
    from reelbot.planner.runner import run_daily

    try:
        result = run_daily(force=args.force)
    except PipelineError:
        return 1
    if result is None:
        return 0
    print(f"\nReel ready: {result.video_path}")
    return 0


def _cmd_queue(args) -> int:
    from reelbot.publish import queue

    if args.queue_command == "list":
        items = queue.load()
        if not items:
            print("Queue is empty. Run 'reelbot generate' to make one.")
            return 0
        print(f"\n{'':4} {'ID':<26} {'FORMAT':<10} {'STATUS':<10} TITLE")
        print("-" * 92)
        for item in items:
            mark = _STATUS_MARK.get(item.status, "[?]")
            print(f"{mark:4} {item.id:<26} {item.format:<10} {item.status:<10} {item.title[:34]}")
        open_items = queue.by_status(*queue.OPEN)
        print(f"\n{len(open_items)} item(s) awaiting action.")
        return 0

    if args.queue_command == "approve":
        if args.id == "all":
            changed = queue.approve_all()
            print(f"Approved {len(changed)} pending item(s).")
            return 0
        try:
            item = queue.approve(args.id)
        except queue.QueueError as exc:
            log.error("%s", exc)
            return 1
        print(f"Approved: {item.title}")
        return 0

    if args.queue_command == "reject":
        try:
            item = queue.reject(args.id)
        except queue.QueueError as exc:
            log.error("%s", exc)
            return 1
        print(f"Rejected: {item.title}")
        return 0

    if args.queue_command == "prune":
        removed = queue.prune()
        print(f"Removed {removed} old entr{'y' if removed == 1 else 'ies'}.")
        return 0

    return 1


def _cmd_publish(_args) -> int:
    from reelbot.planner.runner import publish_approved

    published = publish_approved()
    if not published:
        print("Nothing approved to publish.")
        return 0
    for item in published:
        print(f"Published: {item.title}")
    return 0


def _cmd_schedule(args) -> int:
    from reelbot.planner import calendar

    print("\nWeekly rotation (edit data/schedule.json to change):\n")
    rotation = calendar.load_rotation()
    for day in calendar.WEEKDAY_NAMES:
        print(f"  {day.capitalize():<10} {rotation[day]}")

    print(f"\nNext {args.days} day(s):\n")
    for day, format_key in calendar.upcoming(args.days):
        ran = calendar.already_ran(day)
        note = "  (done)" if ran else ""
        print(f"  {day.strftime('%a %d %b')}  {format_key}{note}")
    return 0


def _cmd_voices(_args) -> int:
    from reelbot.audio.tts import VOICE_ALIASES, VOICE_DESCRIPTIONS

    print("\nAvailable narration voices:\n")
    for alias, voice_id in VOICE_ALIASES.items():
        print(f"  {alias:<8} {voice_id:<22} {VOICE_DESCRIPTIONS.get(alias, '')}")
    print("\nSet one with TTS_VOICE in .env, or --voice on the command line.")
    return 0


def _cmd_web(args) -> int:
    from reelbot.web.app import serve

    banner = (
        f"\nDashboard running at http://{args.host}:{args.port}\n"
        "Localhost only - it has no authentication and can reach your\n"
        "Instagram session. Do not expose it on a network interface.\n"
    )
    print(banner)
    serve(host=args.host, port=args.port)
    return 0


def _cmd_sync(args) -> int:
    from reelbot.publish import sync
    from reelbot.publish.instagram import PublishError

    try:
        result = sync.sync(limit=args.limit)
    except PublishError as exc:
        log.error("%s", exc)
        return 1

    summary = (
        f"\n{len(result.posts)} post(s) on record "
        f"({result.added} new, {result.updated} updated).\n"
    )
    print(summary)
    for post in sync.live_posts()[:12]:
        print(f"  {post.play_count:>7,}  {post.caption_head[:52]}")
    return 0


def _cmd_prune(args) -> int:
    from reelbot.publish import retention

    try:
        plan = retention.build_plan(keep=args.keep, mode=args.mode)
    except retention.RetentionError as exc:
        log.error("%s", exc)
        return 1

    header = (
        f"\nKeep {len(plan.keep)}  |  {args.mode} {len(plan.retire)}  |  "
        f"{len(plan.too_young)} too recent to judge\n"
    )
    print(header)
    for post in plan.retire:
        print(f"  {args.mode:>7}  {post.play_count:>7,}  {post.caption_head[:48]}")
    if not plan.retire:
        print("  nothing to retire.")
        return 0

    if not args.apply:
        print(f"\nDry run. Re-run with --apply to {args.mode} these.")
        return 0

    if args.mode == "delete" and not args.yes_delete_permanently:
        log.error(
            "Deletion is permanent and destroys views, comments and saves. "
            "Pass --yes-delete-permanently if that is really what you want, "
            "or use --mode archive to hide them reversibly."
        )
        return 1

    outcome = retention.apply_plan(
        plan, apply=True, confirm_delete=args.yes_delete_permanently
    )
    print(f"\n{args.mode}d {len(outcome.succeeded)}, failed {len(outcome.failed)}.")
    return 1 if outcome.failed else 0



def _cmd_doctor(_args) -> int:
    from reelbot.render.fonts import ROBOTO_BOLD, emoji_font_path, font_file
    from reelbot.settings import get_settings
    from reelbot.store.paths import PROJECT_ROOT, ensure_dirs

    ensure_dirs()
    settings = get_settings()
    problems = 0

    def check(label: str, ok: bool, detail: str = "", fatal: bool = True) -> None:
        """Report one check. ``detail`` annotates whichever state it describes."""
        nonlocal problems
        mark = "OK  " if ok else ("FAIL" if fatal else "WARN")
        print(f"  [{mark}] {label}{(' - ' + detail) if detail else ''}")
        if not ok and fatal:
            problems += 1

    print(f"\nProject root: {PROJECT_ROOT}\n")

    print("Configuration:")
    check("GEMINI_API_KEY", settings.has_gemini,
          "" if settings.has_gemini else "not set - curated fallback lessons will be used",
          fatal=False)
    check("Instagram credentials", settings.has_instagram,
          "" if settings.has_instagram else "not set - publishing disabled",
          fatal=False)
    print(f"  [INFO] Publish mode : {settings.publish_mode}")
    print(f"  [INFO] Voice        : {settings.tts_voice}")
    print(f"  [INFO] Brand handle : {settings.brand_handle}")

    print("\nDependencies:")
    for module, label in (
        ("edge_tts", "edge-tts"), ("moviepy", "moviepy"), ("PIL", "Pillow"),
        ("numpy", "numpy"), ("google.genai", "google-genai"), ("instagrapi", "instagrapi"),
    ):
        try:
            __import__(module)
            check(label, True)
        except ImportError as exc:
            check(label, False, str(exc))

    print("\nMedia toolchain:")
    try:
        import imageio_ffmpeg
        check("ffmpeg", True, imageio_ffmpeg.get_ffmpeg_version())
    except Exception as exc:  # noqa: BLE001
        check("ffmpeg", False, str(exc))

    print("\nFonts:")
    try:
        check("Roboto", bool(font_file(ROBOTO_BOLD)), font_file(ROBOTO_BOLD))
    except Exception as exc:  # noqa: BLE001
        check("Roboto", False, str(exc))
    emoji = emoji_font_path()
    check("Colour emoji font", emoji is not None,
          emoji or "none found - emoji will render as boxes", fatal=False)

    print(f"\n{'All checks passed.' if problems == 0 else str(problems) + ' problem(s) found.'}")
    return 1 if problems else 0


_COMMANDS = {
    "generate": _cmd_generate,
    "run-daily": _cmd_run_daily,
    "queue": _cmd_queue,
    "publish": _cmd_publish,
    "schedule": _cmd_schedule,
    "web": _cmd_web,
    "sync": _cmd_sync,
    "prune-channel": _cmd_prune,
    "doctor": _cmd_doctor,
    "voices": _cmd_voices,
}


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    setup_logging(verbose=args.verbose)
    try:
        return _COMMANDS[args.command](args)
    except KeyboardInterrupt:
        log.warning("Interrupted.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
