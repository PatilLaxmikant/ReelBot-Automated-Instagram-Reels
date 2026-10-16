"""The content-format registry.

Each format is one Reel template. Keeping their metadata in one table means the
scheduler, renderer, and hashtag picker all agree on what a format *is* instead
of re-deriving it from scattered string comparisons.
"""
from __future__ import annotations

from dataclasses import dataclass

FORMAT_VOCAB = "vocab"
FORMAT_NATIVE = "native"
FORMAT_QUIZ = "quiz"
FORMAT_MISTAKE = "mistake"
FORMAT_CORPORATE = "corporate"
FORMAT_CARD = "card"


@dataclass(frozen=True)
class FormatSpec:
    key: str
    label: str
    badge: str
    #: Card posts are music-only; every other format is narrated.
    narrated: bool
    #: How many teaching items the generator should produce.
    item_count: int
    #: Hashtag pool this format draws its topical tags from.
    topic_tags: tuple[str, ...]


FORMATS: dict[str, FormatSpec] = {
    FORMAT_VOCAB: FormatSpec(
        key=FORMAT_VOCAB,
        label="Vocabulary Upgrade",
        badge="VOCABULARY BOOST",
        narrated=True,
        item_count=3,
        topic_tags=(
            "englishvocabulary", "vocabulary", "wordsmatter", "saythisnotthat",
            "vocabularywords", "wordoftheday", "synonyms", "speaklikeanative",
        ),
    ),
    FORMAT_NATIVE: FormatSpec(
        key=FORMAT_NATIVE,
        label="Textbook vs Native",
        badge="TEXTBOOK VS NATIVE",
        narrated=True,
        item_count=3,
        topic_tags=(
            "nativeenglish", "idioms", "everydayenglish", "englishslang",
            "englishphrases", "conversationalenglish", "phrasalverbs", "reallifeenglish",
        ),
    ),
    FORMAT_QUIZ: FormatSpec(
        key=FORMAT_QUIZ,
        label="3-Second Quiz",
        badge="3-SEC TRICKY QUIZ",
        narrated=True,
        item_count=4,
        topic_tags=(
            "englishquiz", "grammarquiz", "englishtest", "grammarrules",
            "quiztime", "testyourenglish", "englishchallenge", "prepositions",
        ),
    ),
    FORMAT_MISTAKE: FormatSpec(
        key=FORMAT_MISTAKE,
        label="Common Mistake",
        badge="COMMON MISTAKE ALERT",
        narrated=True,
        item_count=2,
        topic_tags=(
            "commonmistakes", "confusingwords", "englishgrammar", "grammartips",
            "englishmistakes", "grammarmatters", "wordchoice", "commonerrors",
        ),
    ),
    FORMAT_CORPORATE: FormatSpec(
        key=FORMAT_CORPORATE,
        label="Workplace English",
        badge="WORKPLACE ENGLISH",
        narrated=True,
        item_count=4,
        topic_tags=(
            "businessenglish", "corporateenglish", "careertips", "workplaceenglish",
            "professionalenglish", "emailtips", "officeenglish", "worklife",
        ),
    ),
    FORMAT_CARD: FormatSpec(
        key=FORMAT_CARD,
        label="Premium Card",
        badge="ENGLISH TIP",
        narrated=False,
        item_count=5,
        topic_tags=(
            "englishcard", "vocabulary", "saythisnotthat", "englishvocabulary",
            "wordoftheday", "sayitbetter", "speakbetterenglish", "englishwriting",
        ),
    ),
}

ALL_FORMATS: list[str] = list(FORMATS)
NARRATED_FORMATS: list[str] = [k for k, spec in FORMATS.items() if spec.narrated]


def get_spec(format_key: str) -> FormatSpec:
    """Look up a format, defaulting to vocab for unknown keys."""
    return FORMATS.get(format_key, FORMATS[FORMAT_VOCAB])


def is_narrated(format_key: str) -> bool:
    return get_spec(format_key).narrated
