"""Caption assembly.

The model writes the hook and the framing; this module owns everything that
must be consistent post to post - the card format's example block, the send
prompt, and (via :mod:`reelbot.content.hashtags`) the tags.

Card posts get special treatment: the card image has room for five swaps but
no room for example sentences, so the examples live in the caption. That is
where the format's actual teaching value ends up.
"""
from __future__ import annotations

from reelbot.formats import FORMAT_CARD

SEND_PREFIX = "\U0001F4E4"  # outbox tray


def _default_body(lesson: dict) -> str:
    title = lesson.get("title", "Learn English")
    return f"{title}\n\nSave this for your next conversation."


def card_examples_block(lesson: dict) -> str:
    """Render the card's swaps as an emoji-led list with example sentences.

    Returns an empty string if no item carries an example, so a model response
    that omits them degrades to just the hook rather than printing blank lines.
    """
    lines: list[str] = []
    for item in lesson.get("items") or []:
        right = str(item.get("right", "")).strip()
        if not right:
            continue
        emoji = str(item.get("emoji", "")).strip()
        example = str(item.get("example", "")).strip()
        bullet = f"{emoji} {right}".strip()
        lines.append(f'{bullet} — "{example}"' if example else bullet)

    if not lines or not any('"' in line for line in lines):
        return ""

    wrong = ""
    for item in lesson.get("items") or []:
        wrong = str(item.get("wrong", "")).strip()
        if wrong:
            break

    header = f'❌ Instead of "{wrong}":' if wrong else "Say this instead:"
    return header + "\n\n" + "\n".join(lines)


def build_caption(lesson: dict, format_key: str) -> str:
    """Caption body + card examples + send prompt, before hashtags."""
    body = str(lesson.get("caption") or _default_body(lesson)).strip()

    if format_key == FORMAT_CARD:
        examples = card_examples_block(lesson)
        if examples:
            body = f"{body}\n\n{examples}"

    send_cta = str(lesson.get("send_cta") or "").strip()
    if send_cta and send_cta.lower() not in body.lower():
        body = f"{body}\n\n{SEND_PREFIX} {send_cta}"

    return body
