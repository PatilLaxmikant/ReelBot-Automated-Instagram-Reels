"""Per-scene slide renderers.

Design rules these follow, all driven by retention/readability constraints
rather than taste:

* One idea per panel, 5-8 words. Big type forces the discipline.
* Elements arrive in beats (see :mod:`reelbot.render.anim`) so something
  changes roughly twice a second instead of a slide sitting static for 8s.
* Nothing is drawn below ``subtitle_top`` or above ``SAFE_TOP``.

Every scene type emitted by :mod:`reelbot.audio.scenes` maps to exactly one
renderer in :data:`SLIDE_RENDERERS`. The mapping is explicit (and covered by a
test) because a silent name mismatch renders a blank frame rather than raising.
"""
from __future__ import annotations

import math
from typing import Callable

from PIL import ImageDraw

from reelbot.formats import (
    FORMAT_CARD,
    FORMAT_CORPORATE,
    FORMAT_MISTAKE,
    FORMAT_NATIVE,
    FORMAT_VOCAB,
)
from reelbot.render.anim import (
    breathe,
    lerp_colour,
    pop,
    reveal,
    rise,
)
from reelbot.render.components import draw_header, eyebrow, header_bottom, panel, subtitle_top
from reelbot.render.text import clean_blank, draw_text, text_width, wrap_text
from reelbot.render.theme import (
    ACCENT_BLUE,
    ACCENT_CYAN,
    ACCENT_GREEN,
    ACCENT_ORANGE,
    ACCENT_RED,
    ACCENT_YELLOW,
    CARD_DARK,
    CONTENT_LEFT,
    CONTENT_RIGHT,
    CONTENT_WIDTH,
    PANEL_DARK,
    RIGHT_BADGE_BG,
    RIGHT_BG,
    RIGHT_BORDER,
    RIGHT_TEXT,
    TEXT_MUTED,
    TEXT_WHITE,
    WIDTH,
    WRONG_BG,
    WRONG_BORDER,
    WRONG_TEXT,
    FontSet,
)

PAD = 40  # inner padding inside a panel


def _glow(base: tuple[int, int, int], amount: int) -> tuple[int, int, int]:
    return tuple(max(0, min(255, channel + amount)) for channel in base)  # type: ignore[return-value]


def _fit_font(text: str, fonts: FontSet, max_width: int, candidates=None):
    """Largest face from ``candidates`` that fits ``text`` on one line."""
    for font in candidates or (fonts.mega, fonts.hero, fonts.title, fonts.body):
        if text_width(text, font) <= max_width:
            return font
    return (candidates or (fonts.body,))[-1]


def _flow(
    draw: ImageDraw.ImageDraw,
    text: str,
    font,
    x: int,
    y: int,
    max_width: int,
    colour: tuple[int, int, int],
    scene_time: float,
    at: float,
    *,
    line_gap: int = 12,
    max_lines: int = 4,
    limit_y: int | None = None,
    background: tuple[int, int, int] = (18, 22, 38),
    stagger: float = 0.09,
) -> int:
    """Draw wrapped text, each line fading and rising in slightly after the last."""
    line_h = font.size + line_gap
    for index, line in enumerate(wrap_text(text, font, max_width)[:max_lines]):
        if limit_y is not None and y + line_h > limit_y:
            break
        amount = reveal(scene_time, at + index * stagger)
        if amount > 0.01:
            draw_text(
                draw,
                (x, y + rise(scene_time, at + index * stagger, 30)),
                line,
                font,
                lerp_colour(background, colour, amount),
            )
        y += line_h
    return y


def _ladder(fonts: FontSet, largest: str = "mega", smallest: str = "small") -> tuple:
    """The type scale from ``largest`` down to ``smallest``, biggest first."""
    scale = [
        ("mega", fonts.mega), ("hero", fonts.hero), ("title", fonts.title),
        ("body", fonts.body), ("caption", fonts.caption), ("small", fonts.small),
    ]
    names = [name for name, _ in scale]
    return tuple(font for name, font in scale[names.index(largest): names.index(smallest) + 1])


def _flow_fit(
    draw: ImageDraw.ImageDraw,
    text: str,
    box: tuple[int, int, int, int],
    colour: tuple[int, int, int],
    scene_time: float,
    at: float,
    *,
    ladder: tuple,
    line_gap: int = 12,
    background: tuple[int, int, int] = (18, 22, 38),
    stagger: float = 0.09,
    centre: bool = False,
) -> int:
    """Draw ``text`` inside ``box`` (x, y, w, h), shrinking the face until it fits.

    Every block on a slide is sized from its content this way. Fixed sizes plus
    a line cap silently truncated model output - including, in one case, the
    blank a quiz question was asking about.
    """
    if not text:
        return box[1]

    x, y, width, height = box
    font = ladder[-1]
    lines = wrap_text(text, font, width)
    for candidate in ladder:
        wrapped = wrap_text(text, candidate, width)
        if len(wrapped) * (candidate.size + line_gap) <= height:
            font, lines = candidate, wrapped
            break

    line_h = font.size + line_gap
    for index, line in enumerate(lines):
        if y + line_h > box[1] + height:
            break
        amount = reveal(scene_time, at + index * stagger)
        if amount > 0.01:
            left = x + (width - int(text_width(line, font))) // 2 if centre else x
            draw_text(
                draw, (left, y + rise(scene_time, at + index * stagger, 30)),
                line, font, lerp_colour(background, colour, amount),
            )
        y += line_h
    return y


def _fit_block(text: str, fonts: FontSet, max_width: int, max_height: int, candidates=None):
    """Largest face whose wrapped text fits inside ``max_height``.

    Model-written copy varies wildly in length; picking the face from the text
    beats truncating it, which is what a fixed size plus a clip did.
    """
    options = candidates or (fonts.caption, fonts.small)
    for font in options:
        lines = wrap_text(text, font, max_width)
        if len(lines) * (font.size + 10) <= max_height:
            return font, lines
    font = options[-1]
    return font, wrap_text(text, font, max_width)[: max(1, max_height // (font.size + 10))]


def _centre_y(draw: ImageDraw.ImageDraw, text: str, font, top: int, height: int) -> int:
    """Draw-origin y that optically centres ``text`` in a band of ``height``.

    Roboto carries generous internal leading, so centring on the em size leaves
    text sitting low and overflowing its panel; this centres the real glyph box.
    """
    box = draw.textbbox((0, 0), text or "X", font=font)
    return top + (height - (box[3] - box[1])) // 2 - box[1]


def _draw_centred(
    draw: ImageDraw.ImageDraw, text: str, font, top: int, height: int,
    colour: tuple[int, int, int], x: int | None = None,
) -> None:
    """Draw ``text`` horizontally centred (unless ``x`` given) and optically centred."""
    left = x if x is not None else (WIDTH - text_width(text, font)) // 2
    draw_text(draw, (left, _centre_y(draw, text, font, top, height)), text, font, colour)


def _ellipsize(text: str, font, max_width: int) -> str:
    """Trim ``text`` to one line of ``max_width``, appending an ellipsis.

    Used where a single line is the design (recap rows). Everything else grows
    or shrinks to fit instead - see :func:`_flow_fit`.
    """
    if text_width(text, font) <= max_width:
        return text
    words = text.split()
    trimmed = ""
    for word in words:
        candidate = f"{trimmed} {word}".strip()
        if text_width(candidate + "...", font) > max_width:
            break
        trimmed = candidate
    return (trimmed + "...") if trimmed else text[:1]


def _strikethrough(draw, x: int, y: int, text: str, font, colour, amount: float) -> None:
    """Animated strike that draws itself left-to-right.

    The line is centred on the glyphs' real bounding box rather than a fraction
    of the em size - Roboto's internal leading pushes the visual centre well
    below the drawing origin, which put the strike through the ascenders.
    """
    if amount <= 0.01 or not text:
        return
    box = draw.textbbox((x, y), text, font=font)
    mid = (box[1] + box[3]) / 2
    full = text_width(text, font)
    draw.line([(x, mid), (x + full * amount, mid)], fill=colour, width=8)


# --- Intro: the hook frame ----------------------------------------------

#: Which two fields hold the thing a format actually teaches. Used to put real
#: content on the opening frame instead of a promise about it.
_PREVIEW_FIELDS: dict[str, tuple[str, str]] = {
    FORMAT_VOCAB: ("basic", "advanced"),
    FORMAT_NATIVE: ("textbook", "native"),
    FORMAT_CORPORATE: ("casual", "corporate"),
    FORMAT_CARD: ("wrong", "right"),
    FORMAT_MISTAKE: ("word", "meaning"),
}

#: How each half of a preview row is marked. Swap formats show a wrong option
#: and a better one, so ❌/✅ is accurate. The mistake format does not: both
#: words are correct English with different meanings, and crossing one out
#: teaches the opposite of the lesson.
_SWAP_STYLE = (("❌", WRONG_TEXT), ("✅", RIGHT_TEXT))
_DEFINE_STYLE = (("•", ACCENT_YELLOW), (" ", TEXT_WHITE))


def _preview_style(format_key: str) -> tuple:
    return _DEFINE_STYLE if format_key == FORMAT_MISTAKE else _SWAP_STYLE


#: How many real swaps the opening frame shows. Two fills the frame without
#: giving the whole lesson away before the items arrive.
PREVIEW_ROWS = 2


def preview_pairs(lesson: dict, limit: int = PREVIEW_ROWS) -> list[tuple[str, str]]:
    """The lesson's first real swaps, as ``(before, after)`` pairs.

    Empty when the format has no pair to show or the items are missing, which
    is the signal for :func:`render_intro` to fall back to generic copy.
    """
    left_key, right_key = _PREVIEW_FIELDS.get(str(lesson.get("format") or ""), ("", ""))
    if not left_key:
        return []

    pairs: list[tuple[str, str]] = []
    for item in lesson.get("items") or []:
        if not isinstance(item, dict):
            continue
        left = str(item.get(left_key) or "").strip()
        right = str(item.get(right_key) or "").strip()
        if left and right:
            pairs.append((left, right))
        if len(pairs) >= limit:
            break
    return pairs


def _preview_lines(text: str, fonts: FontSet, room: int) -> tuple:
    """The largest face that fits ``text``, and its wrapped lines (max two).

    Shrinking before wrapping, and wrapping before ellipsizing, because the
    "after" half of a swap is the payoff - truncating it to "This slipped
    through on..." throws away the only part worth reading.
    """
    for font in (fonts.caption, fonts.small):
        if text_width(text, font) <= room:
            return font, [text]

    font = fonts.small
    lines = wrap_text(text, font, room)
    if len(lines) <= 2:
        return font, lines
    return font, [lines[0], _ellipsize(" ".join(lines[1:]), font, room)]


def _draw_preview(
    draw: ImageDraw.ImageDraw, pairs: list[tuple[str, str]], top: int,
    scene_time: float, fonts: FontSet, first_at: float, limit_y: int,
    style: tuple = _SWAP_STYLE,
) -> None:
    """Draw ``pairs`` as two marked lines each, in ``style``'s markers.

    Stacked rather than joined by an arrow: neither Roboto nor Segoe UI Emoji
    carries a usable arrow glyph, and a stacked pair reads at thumbnail size
    where one long line does not.
    """
    (left_marker, left_colour), (right_marker, right_colour) = style
    indent = int(text_width("❌ ", fonts.caption)) + 12
    room = CONTENT_WIDTH - indent
    y = top

    for index, (left, right) in enumerate(pairs):
        for marker, text, colour, beat in (
            (left_marker, left, left_colour, first_at + index * 0.26),
            (right_marker, right, right_colour, first_at + index * 0.26 + 0.13),
        ):
            font, lines = _preview_lines(text, fonts, room)
            line_h = font.size + 10
            if y + line_h * len(lines) > limit_y:
                return

            amount = reveal(scene_time, beat)
            if amount > 0.01:
                offset = rise(scene_time, beat, 30)
                shade = lerp_colour((18, 22, 38), colour, amount)
                draw_text(draw, (CONTENT_LEFT, y + offset), marker, fonts.caption, shade)
                for line_index, line in enumerate(lines):
                    draw_text(
                        draw, (CONTENT_LEFT + indent, y + offset + line_index * line_h),
                        line, font, shade,
                    )
            y += line_h * len(lines) + 6
        y += 30


def render_intro(draw: ImageDraw.ImageDraw, scene: dict, scene_time: float, fonts: FontSet) -> None:
    """The opening frame. It has to carry the lesson, not announce it.

    It used to draw the title plus three fixed bullets - "Textbook English",
    "What natives really say", "Use it today" - identical on every reel and
    true of every reel, so the first 6-8 seconds contained no lesson at all.
    Measured on real output: the first actual phrase appeared at 8.2s on a
    corporate reel and 6.2s on a mistake reel. The one format that already
    opened on its content, the quiz, is also the one that pulled 1,188 views.
    """
    data = scene.get("data", {})
    draw_header(draw, data.get("badge", "DAILY ENGLISH"), "", fonts)

    top = header_bottom(fonts) + 60
    title = clean_blank(data.get("title", "Level Up Your English"))

    pairs = preview_pairs(data)
    # The title yields room to the content when there is content to show.
    title_box = 340 if pairs else 470
    y = _flow_fit(
        draw, title, (CONTENT_LEFT, top, CONTENT_WIDTH, title_box),
        TEXT_WHITE, scene_time, 0.0,
        ladder=_ladder(fonts, "mega", "body"), line_gap=16,
    )

    subtitle = data.get("subtitle") or "Sound natural, not textbook"
    amount = reveal(scene_time, 0.22)
    if amount > 0.01:
        bar_y = y + 24
        draw.rounded_rectangle(
            [CONTENT_LEFT, bar_y, CONTENT_LEFT + int(CONTENT_WIDTH * amount), bar_y + 10],
            radius=5, fill=ACCENT_CYAN,
        )
        y = _flow_fit(
            draw, subtitle, (CONTENT_LEFT, bar_y + 36, CONTENT_WIDTH, 130 if pairs else 170),
            ACCENT_CYAN, scene_time, 0.28, ladder=_ladder(fonts, "body", "small"),
        )

    if pairs:
        _draw_preview(
            draw, pairs, y + 40, scene_time, fonts,
            first_at=0.5, limit_y=subtitle_top(fonts) - 20,
            style=_preview_style(str(data.get("format") or "")),
        )
        return

    # No usable items: fall back to the generic promises rather than a bare title.
    y += 50
    for index, bullet in enumerate(
        ("❌  Textbook English", "✅  What natives really say", "\U0001F4A1  Use it today")
    ):
        at = 1.05 + index * 0.32
        amount = reveal(scene_time, at)
        if amount <= 0.01:
            continue
        offset = rise(scene_time, at, 36)
        draw_text(
            draw, (CONTENT_LEFT + 6, y + offset), bullet, fonts.body,
            lerp_colour((18, 22, 38), TEXT_WHITE, amount),
        )
        y += fonts.body.size + 26


# --- Comparison item slides (vocab / native / corporate) -----------------

def _render_comparison(
    draw: ImageDraw.ImageDraw,
    scene: dict,
    scene_time: float,
    fonts: FontSet,
    *,
    badge: str,
    wrong_label: str,
    wrong_key: str,
    right_label: str,
    right_key: str,
    meta_label: str,
    meta_key: str,
    example_label: str,
    default_total: int,
) -> None:
    """'Don't say X, say Y' - the workhorse layout for three formats.

    Beats: wrong panel -> strike -> right panel -> hero word pops -> meaning
    -> example. Roughly one change every half second for the first 3 seconds.
    """
    item = scene.get("data", {})
    idx = scene.get("item_index", 0)
    total = scene.get("total_items", default_total)
    draw_header(draw, badge, f"{idx + 1}/{total}", fonts)

    bottom = subtitle_top(fonts) - 20
    top = header_bottom(fonts) + 40

    # --- Panel 1: the phrase to drop
    wrong_h = 280
    panel(
        draw, (CONTENT_LEFT, top, CONTENT_RIGHT, top + wrong_h),
        fill=WRONG_BG, outline=WRONG_BORDER, amount=reveal(scene_time, 0.0), radius=34,
    )
    eyebrow(draw, (CONTENT_LEFT + PAD, top + 34), wrong_label, fonts, WRONG_TEXT, scene_time, 0.08)

    wrong_text = str(item.get(wrong_key, "")).strip()
    wrong_width = CONTENT_WIDTH - PAD * 2
    wrong_y = top + 112
    wrong_ladder = _ladder(fonts, "hero", "caption")
    _flow_fit(
        draw, wrong_text, (CONTENT_LEFT + PAD, wrong_y, wrong_width, wrong_h - 128),
        TEXT_WHITE, scene_time, 0.15, ladder=wrong_ladder, background=WRONG_BG,
    )
    # Strike only the first rendered line, at whatever size actually got used.
    wrong_font = next(
        (f for f in wrong_ladder
         if len(wrap_text(wrong_text, f, wrong_width)) * (f.size + 12) <= wrong_h - 128),
        wrong_ladder[-1],
    )
    _strikethrough(
        draw, CONTENT_LEFT + PAD, wrong_y,
        (wrap_text(wrong_text, wrong_font, wrong_width) or [""])[0],
        wrong_font, ACCENT_RED, reveal(scene_time, 0.55, 0.35),
    )

    # --- Panel 2: the upgrade
    right_top = top + wrong_h + 34
    right_h = 460
    panel(
        draw, (CONTENT_LEFT, right_top, CONTENT_RIGHT, right_top + right_h),
        fill=RIGHT_BG, outline=_glow(RIGHT_BORDER, breathe(scene_time)),
        amount=reveal(scene_time, 0.85), radius=34,
    )
    eyebrow(
        draw, (CONTENT_LEFT + PAD, right_top + 34), right_label, fonts,
        RIGHT_TEXT, scene_time, 0.95, background=RIGHT_BG,
    )

    hero_text = str(item.get(right_key, "")).strip()
    meta = str(item.get(meta_key, "")).strip()
    meta_h = 150 if meta else 20

    if pop(scene_time, 1.15, 0.5) > 0.01:
        _flow_fit(
            draw, hero_text,
            (CONTENT_LEFT + PAD, right_top + 112, CONTENT_WIDTH - PAD * 2,
             right_h - 130 - meta_h),
            TEXT_WHITE, scene_time, 1.15,
            ladder=_ladder(fonts, "mega", "body"), background=RIGHT_BG,
        )

    if meta:
        _flow_fit(
            draw, f"{meta_label}: {meta}",
            (CONTENT_LEFT + PAD, right_top + right_h - meta_h - 8,
             CONTENT_WIDTH - PAD * 2, meta_h),
            ACCENT_CYAN, scene_time, 1.85,
            ladder=_ladder(fonts, "caption", "small"), line_gap=8, background=RIGHT_BG,
        )

    # --- Panel 3: it in a real sentence
    ex_top = right_top + right_h + 34
    if ex_top + 180 <= bottom:
        panel(
            draw, (CONTENT_LEFT, ex_top, CONTENT_RIGHT, bottom),
            fill=PANEL_DARK, outline=(51, 65, 85), amount=reveal(scene_time, 2.5),
            radius=30, width=3,
        )
        eyebrow(
            draw, (CONTENT_LEFT + PAD, ex_top + 30), example_label, fonts,
            ACCENT_YELLOW, scene_time, 2.6, background=PANEL_DARK,
        )
        _flow_fit(
            draw, '"' + str(item.get("example", "")) + '"',
            (CONTENT_LEFT + PAD, ex_top + 100, CONTENT_WIDTH - PAD * 2,
             bottom - ex_top - 118),
            TEXT_WHITE, scene_time, 2.75,
            ladder=_ladder(fonts, "body", "small"), background=PANEL_DARK,
        )


def render_vocab_item(draw, scene, scene_time, fonts):
    _render_comparison(
        draw, scene, scene_time, fonts,
        badge="VOCABULARY",
        wrong_label="❌  STOP SAYING", wrong_key="basic",
        right_label="✅  SAY THIS", right_key="advanced",
        meta_label="Means", meta_key="nuance",
        example_label="\U0001F4AC IN A SENTENCE",
        default_total=3,
    )


def render_native_item(draw, scene, scene_time, fonts):
    _render_comparison(
        draw, scene, scene_time, fonts,
        badge="NATIVE ENGLISH",
        wrong_label="\U0001F4D5  TEXTBOOK", wrong_key="textbook",
        right_label="\U0001F5E3️  NATIVES SAY", right_key="native",
        meta_label="Use it", meta_key="context",
        example_label="\U0001F4AC IN A SENTENCE",
        default_total=3,
    )


def render_corporate_item(draw, scene, scene_time, fonts):
    _render_comparison(
        draw, scene, scene_time, fonts,
        badge="WORK ENGLISH",
        wrong_label="❌  TOO BLUNT", wrong_key="casual",
        right_label="\U0001F4BC  SAY THIS", right_key="corporate",
        meta_label="When", meta_key="situation",
        example_label="\U0001F4AC IN AN EMAIL",
        default_total=4,
    )


# --- Quiz ----------------------------------------------------------------

def render_quiz(draw: ImageDraw.ImageDraw, scene: dict, scene_time: float, fonts: FontSet) -> None:
    data = scene.get("data", {})
    scene_type = scene.get("type", "quiz_question")
    is_countdown = scene_type == "quiz_countdown"
    is_reveal = scene_type == "quiz_reveal"

    draw_header(draw, "ENGLISH QUIZ", "CAN YOU?", fonts)
    bottom = subtitle_top(fonts) - 20
    top = header_bottom(fonts) + 40

    # The question box grows with the question, but never past the room the
    # options need. Truncating here once cut off the blank being asked about.
    question = clean_blank(data.get("question", "Fill in the blank: _"))
    q_width = CONTENT_WIDTH - PAD * 2
    q_ladder = _ladder(fonts, "title", "small")
    option_count = min(len(data.get("options", [])) or 4, 4)

    # Budget the column explicitly: panel chrome + gap + options + whatever the
    # countdown needs. Under-reserving here once let the countdown box overlap
    # the last option when a long question pushed everything down.
    Q_CHROME, Q_GAP, OPTION_H, OPTION_GAP = 110, 30, 118, 14
    COUNTDOWN_H, COUNTDOWN_GAP = 250, 20
    options_block = (OPTION_H + OPTION_GAP) * option_count
    tail = (COUNTDOWN_H + COUNTDOWN_GAP) if is_countdown else 20
    q_max_h = max(120, bottom - top - Q_CHROME - Q_GAP - options_block - tail)

    q_font = next(
        (f for f in q_ladder if len(wrap_text(question, f, q_width)) * (f.size + 12) <= q_max_h),
        q_ladder[-1],
    )
    q_h = Q_CHROME + len(wrap_text(question, q_font, q_width)) * (q_font.size + 12)

    panel(
        draw, (CONTENT_LEFT, top, CONTENT_RIGHT, top + q_h),
        fill=CARD_DARK, outline=ACCENT_BLUE, amount=reveal(scene_time, 0.0), radius=32, width=4,
    )
    eyebrow(draw, (CONTENT_LEFT + PAD, top + 30), "❓  FILL THE BLANK", fonts, ACCENT_CYAN, scene_time, 0.05)
    _flow_fit(
        draw, question, (CONTENT_LEFT + PAD, top + 100, q_width, q_h - 110),
        TEXT_WHITE, scene_time, 0.15, ladder=q_ladder, background=CARD_DARK,
    )

    options = data.get("options", [])[:4]
    correct = str(data.get("correct_option", "A")).strip().upper()
    y = top + q_h + Q_GAP
    option_h, gap = OPTION_H, OPTION_GAP

    def _is_correct(text: str) -> bool:
        upper = text.strip().upper()
        return upper.startswith(correct) or f"{correct})" in upper

    if is_reveal:
        # Reveal shows only the answer, big. Re-listing the wrong options
        # steals the room the explanation needs and buries the payoff.
        answer = next(
            (clean_blank(o) for o in options if _is_correct(clean_blank(o))),
            str(data.get("correct_text") or correct),
        )
        answer_h = 230
        panel(
            draw, (CONTENT_LEFT, y, CONTENT_RIGHT, y + answer_h),
            fill=(10, 48, 30), outline=_glow(ACCENT_GREEN, breathe(scene_time, 6.0, 18)),
            amount=pop(scene_time, 0.1, 0.45), radius=32, width=6,
        )
        eyebrow(
            draw, (CONTENT_LEFT + PAD, y + 26), "✅  CORRECT ANSWER", fonts,
            RIGHT_TEXT, scene_time, 0.2, background=(10, 48, 30),
        )
        answer_font = _fit_font(
            answer, fonts, CONTENT_WIDTH - PAD * 2, _ladder(fonts, "mega", "body")
        )
        if reveal(scene_time, 0.35) > 0.01:
            _draw_centred(
                draw, answer, answer_font, y + 90, answer_h - 110, TEXT_WHITE,
                x=CONTENT_LEFT + PAD,
            )
        y += answer_h + 26

        box_top = y
        panel(
            draw, (CONTENT_LEFT, box_top, CONTENT_RIGHT, bottom),
            fill=(20, 34, 78), outline=ACCENT_BLUE, amount=reveal(scene_time, 0.9),
            radius=30, width=4,
        )
        eyebrow(
            draw, (CONTENT_LEFT + PAD, box_top + 28), "\U0001F4A1  WHY", fonts,
            ACCENT_CYAN, scene_time, 1.0, background=(20, 34, 78),
        )
        _flow_fit(
            draw, str(data.get("explanation", "")),
            (CONTENT_LEFT + PAD, box_top + 104, CONTENT_WIDTH - PAD * 2,
             bottom - box_top - 118),
            (226, 236, 250), scene_time, 1.15,
            ladder=_ladder(fonts, "body", "small"), line_gap=10, background=(20, 34, 78),
        )
        return

    # Question and countdown scenes list the options; reveal returned above.
    for index, option in enumerate(options):
        text = clean_blank(option)
        at = 0.5 + index * 0.18

        fill = CARD_DARK
        border = ACCENT_BLUE if is_countdown else (55, 68, 92)
        colour, width = TEXT_WHITE, 3

        amount = reveal(scene_time, at)
        panel(
            draw, (CONTENT_LEFT, y, CONTENT_RIGHT, y + option_h),
            fill=fill, outline=border, amount=amount, radius=24, width=width,
        )
        if amount > 0.01:
            # Fit each option to the panel width; long distractors used to run
            # straight off the right edge of the canvas.
            option_font = _fit_font(
                text, fonts, CONTENT_WIDTH - PAD * 2, _ladder(fonts, "title", "small")
            )
            _draw_centred(
                draw, text, option_font, y, option_h,
                lerp_colour(fill, colour, amount), x=CONTENT_LEFT + PAD,
            )
        y += option_h + gap

    if is_countdown:
        duration = max(scene.get("duration", 3.0), 0.1)
        remaining = max(0.0, min(1.0, 1.0 - scene_time / duration))
        seconds_left = max(1, min(3, math.ceil(remaining * 3)))
        colour, background = {
            3: (ACCENT_YELLOW, (48, 38, 12)),
            2: (ACCENT_ORANGE, (56, 30, 12)),
        }.get(seconds_left, (ACCENT_RED, (58, 16, 24)))

        # A big ticking number reads as motion even with the sound off.
        digit = str(seconds_left)
        # Sits below the options, never on top of them; the budget above
        # guarantees the room exists.
        digit_band, bar_h = 170, 16
        box_top = y + COUNTDOWN_GAP
        box_h = min(COUNTDOWN_H, bottom - box_top)
        panel(
            draw, (CONTENT_LEFT, box_top, CONTENT_RIGHT, box_top + box_h),
            fill=background, outline=_glow(colour, breathe(scene_time, 9.0, 20)),
            amount=1.0, radius=30, width=5,
        )
        _draw_centred(draw, digit, fonts.mega, box_top + 10, digit_band, colour)

        bar_y = box_top + box_h - bar_h - 26
        draw.rounded_rectangle(
            [CONTENT_LEFT + 34, bar_y, CONTENT_RIGHT - 34, bar_y + bar_h], radius=8, fill=(30, 41, 59),
        )
        fill_w = int((CONTENT_WIDTH - 68) * remaining)
        if fill_w > 0:
            draw.rounded_rectangle(
                [CONTENT_LEFT + 34, bar_y, CONTENT_LEFT + 34 + fill_w, bar_y + bar_h],
                radius=8, fill=colour,
            )


# --- Confusing words -----------------------------------------------------

def render_mistake_word(
    draw: ImageDraw.ImageDraw, scene: dict, scene_time: float, fonts: FontSet
) -> None:
    item = scene.get("data", {})
    idx = scene.get("word_index", 0)
    total = scene.get("total_words", 2)
    first = idx == 0

    draw_header(draw, "COMMON MISTAKE", f"{idx + 1}/{total}", fonts)
    bottom = subtitle_top(fonts) - 20
    top = header_bottom(fonts) + 40

    accent = ACCENT_ORANGE if first else ACCENT_GREEN
    background = (44, 26, 12) if first else RIGHT_BG

    panel(
        draw, (CONTENT_LEFT, top, CONTENT_RIGHT, bottom),
        fill=background, outline=_glow(accent, breathe(scene_time)),
        amount=reveal(scene_time, 0.0), radius=36, width=5,
    )

    word = str(item.get("word", "")).upper()
    y = _flow_fit(
        draw, word, (CONTENT_LEFT + PAD, top + 56, CONTENT_WIDTH - PAD * 2, 170),
        TEXT_WHITE, scene_time, 0.12,
        ladder=_ladder(fonts, "mega", "title"), background=background,
    )

    word_type = str(item.get("type", "")).strip()
    if word_type:
        amount = reveal(scene_time, 0.7)
        if amount > 0.01:
            chip_w = text_width(word_type.upper(), fonts.label) + 44
            draw.rounded_rectangle(
                [CONTENT_LEFT + PAD, y + 14, CONTENT_LEFT + PAD + chip_w, y + 14 + fonts.label.size + 26],
                radius=16, fill=lerp_colour(background, (48, 62, 88), amount),
            )
            draw_text(
                draw, (CONTENT_LEFT + PAD + 22, y + 26), word_type.upper(), fonts.label,
                lerp_colour(background, ACCENT_CYAN, amount),
            )
            y += fonts.label.size + 50

    y = _flow_fit(
        draw, str(item.get("meaning", "")),
        (CONTENT_LEFT + PAD, y + 24, CONTENT_WIDTH - PAD * 2, 210),
        accent, scene_time, 1.0,
        ladder=_ladder(fonts, "title", "small"), background=background,
    )

    ex_top = y + 40
    if ex_top + 150 <= bottom - 20:
        panel(
            draw, (CONTENT_LEFT + PAD, ex_top, CONTENT_RIGHT - PAD, bottom - 30),
            fill=(12, 16, 30), outline=(52, 64, 88), amount=reveal(scene_time, 1.9),
            radius=26, width=3,
        )
        eyebrow(
            draw, (CONTENT_LEFT + PAD * 2, ex_top + 26), "\U0001F4AC EXAMPLE", fonts,
            ACCENT_YELLOW, scene_time, 2.0, background=(12, 16, 30),
        )
        _flow_fit(
            draw, '"' + str(item.get("example", "")) + '"',
            (CONTENT_LEFT + PAD * 2, ex_top + 92, CONTENT_WIDTH - PAD * 4,
             bottom - ex_top - 140),
            TEXT_WHITE, scene_time, 2.15,
            ladder=_ladder(fonts, "body", "small"), background=(12, 16, 30),
        )


def render_mistake_trick(
    draw: ImageDraw.ImageDraw, scene: dict, scene_time: float, fonts: FontSet
) -> None:
    """The memory-trick payoff - the most saveable frame in the reel."""
    data = scene.get("data", {})
    draw_header(draw, "\U0001F9E0 MEMORY TRICK", "SAVE THIS", fonts)
    bottom = subtitle_top(fonts) - 20
    top = header_bottom(fonts) + 40

    panel(
        draw, (CONTENT_LEFT, top, CONTENT_RIGHT, bottom),
        fill=(20, 34, 78), outline=_glow(ACCENT_BLUE, breathe(scene_time)),
        amount=reveal(scene_time, 0.0), radius=36, width=5,
    )

    rule = str(data.get("rule") or data.get("outro_script") or "Remember this rule")
    y = _flow_fit(
        draw, rule,
        (CONTENT_LEFT + PAD, top + 70, CONTENT_WIDTH - PAD * 2, bottom - top - 320),
        TEXT_WHITE, scene_time, 0.15,
        ladder=_ladder(fonts, "hero", "small"), line_gap=16, background=(20, 34, 78),
    )

    cta_top = max(y + 60, bottom - 220)
    panel(
        draw, (CONTENT_LEFT + PAD, cta_top, CONTENT_RIGHT - PAD, bottom - 30),
        fill=(10, 40, 28), outline=_glow(ACCENT_GREEN, breathe(scene_time, 4.0, 14)),
        amount=reveal(scene_time, 1.2), radius=28, width=4,
    )
    eyebrow(
        draw, (CONTENT_LEFT + PAD * 2, cta_top + 30), "\U0001F4BE SAVE IT", fonts,
        RIGHT_TEXT, scene_time, 1.35, background=(10, 40, 28),
    )
    _flow(
        draw, "You will forget this by tomorrow.", fonts.body, CONTENT_LEFT + PAD * 2,
        cta_top + 96, CONTENT_WIDTH - PAD * 4, TEXT_WHITE, scene_time, 1.5,
        max_lines=2, limit_y=bottom - 40, background=(10, 40, 28),
    )


# --- Outro ---------------------------------------------------------------

def render_outro(draw: ImageDraw.ImageDraw, scene: dict, scene_time: float, fonts: FontSet) -> None:
    """Recap the upgrades as a scannable list, then ask for the save."""
    data = scene.get("data", {})
    draw_header(draw, "RECAP", "SAVE & SHARE", fonts)
    bottom = subtitle_top(fonts) - 20
    top = header_bottom(fonts) + 40

    items = (data.get("items") or [])[:4]
    row_h, row_gap, chip_d = 128, 16, 60
    list_h = len(items) * (row_h + row_gap)

    for index, item in enumerate(items):
        heading = str(
            item.get("corporate") or item.get("advanced") or item.get("native")
            or item.get("word") or item.get("right") or f"Point {index + 1}"
        )
        at = 0.15 + index * 0.28
        amount = reveal(scene_time, at)
        if amount <= 0.01:
            continue
        y = top + index * (row_h + row_gap) + rise(scene_time, at, 40)

        panel(
            draw, (CONTENT_LEFT, y, CONTENT_RIGHT, y + row_h),
            fill=PANEL_DARK, outline=(52, 66, 92), amount=amount, radius=24, width=3,
        )
        chip_y = y + (row_h - chip_d) // 2
        draw.ellipse(
            [CONTENT_LEFT + 26, chip_y, CONTENT_LEFT + 26 + chip_d, chip_y + chip_d],
            fill=lerp_colour(PANEL_DARK, RIGHT_BADGE_BG, amount),
        )
        chip = f"{index + 1}"
        _draw_centred(
            draw, chip, fonts.label, chip_y, chip_d,
            lerp_colour(PANEL_DARK, RIGHT_TEXT, amount),
            x=CONTENT_LEFT + 26 + (chip_d - int(text_width(chip, fonts.label))) // 2,
        )

        # Fit to the row and centre optically. A fixed face drawn at a fixed
        # offset overflowed the panel on every recap row.
        heading_x = CONTENT_LEFT + 26 + chip_d + 28
        heading_width = CONTENT_RIGHT - heading_x - 28
        heading_font = _fit_font(
            heading, fonts, heading_width, _ladder(fonts, "title", "small")
        )
        _draw_centred(
            draw, _ellipsize(heading, heading_font, heading_width), heading_font,
            y, row_h, lerp_colour(PANEL_DARK, TEXT_WHITE, amount), x=heading_x,
        )

    cta_top = min(top + list_h + 40, bottom - 340)
    panel(
        draw, (CONTENT_LEFT, cta_top, CONTENT_RIGHT, bottom),
        fill=(20, 34, 78), outline=_glow(ACCENT_CYAN, breathe(scene_time, 4.0, 14)),
        amount=reveal(scene_time, 1.5), radius=32, width=5,
    )
    # The send prompt, not "comment below": DM sends are the heaviest-weighted
    # reel signal, and this account was asking for the wrong action entirely.
    eyebrow(
        draw, (CONTENT_LEFT + PAD, cta_top + 30), "\U0001F4E4 SEND THIS TO", fonts,
        ACCENT_YELLOW, scene_time, 1.6, background=(20, 34, 78),
    )

    save_line = "\U0001F4BE Save it for later"
    save_h = fonts.caption.size + 26
    send_cta = str(data.get("send_cta") or "Send this to someone who needs it")
    _flow_fit(
        draw, send_cta,
        (CONTENT_LEFT + PAD, cta_top + 104, CONTENT_WIDTH - PAD * 2,
         bottom - cta_top - 134 - save_h),
        TEXT_WHITE, scene_time, 1.75,
        ladder=_ladder(fonts, "title", "small"), background=(20, 34, 78),
    )
    _flow_fit(
        draw, save_line,
        (CONTENT_LEFT + PAD, bottom - save_h - 24, CONTENT_WIDTH - PAD * 2, save_h),
        TEXT_MUTED, scene_time, 2.1,
        ladder=_ladder(fonts, "caption", "small"), background=(20, 34, 78),
    )


# --- Registry ------------------------------------------------------------

SlideRenderer = Callable[[ImageDraw.ImageDraw, dict, float, FontSet], None]

#: Every scene type emitted by reelbot.audio.scenes must appear here.
SLIDE_RENDERERS: dict[str, SlideRenderer] = {
    "vocab_intro": render_intro,
    "vocab_item": render_vocab_item,
    "vocab_outro": render_outro,
    "native_intro": render_intro,
    "native_item": render_native_item,
    "native_outro": render_outro,
    "quiz_question": render_quiz,
    "quiz_countdown": render_quiz,
    "quiz_reveal": render_quiz,
    "mistake_intro": render_intro,
    "mistake_word": render_mistake_word,
    "mistake_trick": render_mistake_trick,
    "corporate_intro": render_intro,
    "corporate_item": render_corporate_item,
    "corporate_outro": render_outro,
}


def render_slide(
    draw: ImageDraw.ImageDraw, scene: dict, scene_time: float, fonts: FontSet
) -> None:
    """Dispatch one scene to its renderer, falling back to the intro layout."""
    renderer = SLIDE_RENDERERS.get(scene.get("type", ""), render_intro)
    renderer(draw, scene, scene_time, fonts)
