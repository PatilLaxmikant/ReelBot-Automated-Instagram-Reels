"""Prompt assembly for the Gemini lesson generator.

The per-format instruction blocks live in ``format_prompts.json`` beside this
module so they can be tuned without touching code. Edit that file to change
the editorial voice of a format.
"""
from __future__ import annotations

import functools
import json
from pathlib import Path

_PROMPT_FILE = Path(__file__).with_name("format_prompts.json")

SYSTEM_PREAMBLE = (
    "You are an expert social media English coach creating viral, high-retention "
    "educational Reels for Instagram.\n"
    "Target Audience: Everyday learners wanting to speak naturally, sound confident, "
    "and master workplace English.\n"
)

#: Hard limits. Retention data is the reason these are numeric rather than
#: adjectives: reels live or die on the first 3 seconds, the sweet spot is
#: 8-19 seconds total, and on-screen text is unreadable past ~8 words at the
#: sizes required for mobile. Long scripts made 45-50s reels nobody finished.
LENGTH_RULES = (
    "LENGTH LIMITS (these are hard limits, not suggestions):\n"
    "- 'title': MAXIMUM 6 words. It is rendered very large on screen. Punchy, not descriptive.\n"
    "- 'subtitle': MAXIMUM 5 words.\n"
    "- 'intro_script': MAXIMUM 20 spoken words. It must land the hook in under 3 seconds.\n"
    "- Each item 'narration': MAXIMUM 25 spoken words. One idea only.\n"
    "- 'outro_script': MAXIMUM 18 spoken words.\n"
    "- 'example': MAXIMUM 10 words. It must fit on screen in two lines of large text.\n"
    "- 'nuance' / 'context' / 'situation': MAXIMUM 6 words.\n"
    "- 'explanation' (quiz): MAXIMUM 25 words. State the rule, no preamble.\n"
    "- 'advanced' / 'native' / 'corporate' / 'right': ideally ONE word or a short phrase.\n"
    "  These are rendered at the largest size on screen and must not wrap past two lines.\n"
    "- 'send_cta': MAXIMUM 12 words. See guideline 2 below.\n"
)

GROWTH_RULES = (
    f"{LENGTH_RULES}\n"
    "Key Growth Guidelines:\n"
    "1. The first spoken line IS the hook. Open with the contrast, claim, or question -\n"
    "   never with a greeting, a preamble, or 'in this video'.\n"
    "   Keep 'intro_script' to ONE short sentence, at most 10 words. The opening slide\n"
    "   stays on screen for exactly as long as this line takes to say, and a long intro\n"
    "   holds a viewer on a title card instead of the lesson. Anything past the first\n"
    "   sentence is discarded before narration.\n"
    "2. ALWAYS return a 'send_cta' field: one line telling the viewer to send the reel\n"
    "   to a SPECIFIC kind of person, tied to this lesson's actual content.\n"
    "   Instagram weights DM sends far above likes, and a generic 'share this' does not\n"
    "   work - the viewer has to picture one real person.\n"
    "   Good: Send this to the friend who always says 'very busy'\n"
    "   Good: Send this to someone who still mixes these two up\n"
    "   Bad:  Share this with your friends   (no specific person)\n"
    "3. Write for someone watching on mute. The on-screen words must carry the lesson\n"
    "   on their own; narration reinforces, it does not replace them.\n"
    "4. NEVER mention explicit level codes (No C1, C2, B1, B2, Advanced, Beginner).\n"
    "5. For Quizzes, use strictly a single '_' for blanks.\n"
    "6. Narration must sound spoken, not written: contractions, short sentences, no lists.\n"
    "7. Always include a Save-Bait CTA in the outro and caption "
    "('Save this for later practice').\n"
    "8. Write captions WITHOUT hashtags - hashtags are appended separately.\n"
    "9. Return STRICT JSON only matching the requested schema."
)


@functools.lru_cache(maxsize=1)
def _format_prompts() -> dict[str, str]:
    with open(_PROMPT_FILE, "r", encoding="utf-8") as handle:
        return json.load(handle)


def format_instructions(format_key: str) -> str:
    """The per-format instruction block, or an empty string if unknown."""
    return _format_prompts().get(format_key, "")


def build_prompt(
    format_key: str,
    recent_topics: list[str],
    *,
    hook_ban: str = "",
    insist: bool = False,
    banned_subjects: list[str] | None = None,
) -> str:
    """Assemble the full generation prompt for one format.

    Args:
        recent_topics: recent lesson titles, so the model avoids repeating them.
        hook_ban: clause from :mod:`reelbot.content.hooks` banning recently used
            title *shapes* - topic variety and hook variety are separate problems.
        insist: set on a retry after the model reused a banned hook anyway.
        banned_subjects: topics the account has already covered, normalised by
            :mod:`reelbot.store.history`. Titles alone under-report this: the
            same lesson has shipped twice under two different headlines.
    """
    avoid = ", ".join(recent_topics) if recent_topics else "None"
    subject_ban = ""
    if banned_subjects:
        subject_ban = (
            "TOPIC BAN (hard requirement):\n"
            "This account has already taught the subjects below. Teaching any of "
            "them again, under any title or in any format, is a failure:\n"
            f"  {', '.join(sorted(banned_subjects))}\n\n"
        )
    emphasis = (
        "\nYOUR PREVIOUS ATTEMPT REUSED A BANNED TITLE PATTERN. Pick a genuinely "
        "different hook shape this time - this is the most important instruction "
        "in this prompt.\n" if insist else ""
    )
    return (
        f"{SYSTEM_PREAMBLE}"
        f"{format_instructions(format_key)}\n"
        f"Avoid repeating any of these recently used topics: {avoid}.\n\n"
        f"{subject_ban}{hook_ban}{emphasis}\n"
        f"{GROWTH_RULES}"
    )
