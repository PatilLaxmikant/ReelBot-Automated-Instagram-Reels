"""Lesson validation and fallback selection."""
from __future__ import annotations

import copy

import pytest

from reelbot.content import fallbacks
from reelbot.content.captions import SEND_PREFIX
from reelbot.content.generator import ValidationError, validate_lesson
from reelbot.content.prompts import build_prompt, format_instructions
from reelbot.formats import ALL_FORMATS


class TestFallbacks:
    @pytest.mark.parametrize("format_key", ALL_FORMATS)
    def test_every_format_has_a_usable_fallback(self, format_key):
        lesson = fallbacks.pick(format_key)
        assert lesson["format"] == format_key
        validate_lesson(lesson, format_key)

    def test_returns_a_copy_callers_can_mutate(self):
        first = fallbacks.pick("vocab")
        first["title"] = "mutated"
        assert fallbacks.pick("vocab")["title"] != "mutated"

    def test_prefers_a_lesson_not_in_history(self):
        pool = fallbacks._lessons()["quiz"]
        assert len(pool) >= 2, "this test needs at least two quiz fallbacks"
        used = pool[0]["title"]
        for _ in range(12):
            assert fallbacks.pick("quiz", history=[used])["title"] != used

    def test_falls_back_to_the_pool_when_all_are_used(self):
        used = [lesson["title"] for lesson in fallbacks._lessons()["quiz"]]
        assert fallbacks.pick("quiz", history=used)["title"] in used


class TestValidation:
    @pytest.mark.parametrize("format_key", ALL_FORMATS)
    def test_missing_title_is_rejected(self, format_key):
        lesson = fallbacks.pick(format_key)
        lesson["title"] = ""
        with pytest.raises(ValidationError, match="title"):
            validate_lesson(lesson, format_key)

    def test_non_dict_is_rejected(self):
        with pytest.raises(ValidationError):
            validate_lesson(["not", "a", "dict"], "vocab")

    def test_too_few_items_is_rejected(self):
        lesson = fallbacks.pick("vocab")
        lesson["items"] = lesson["items"][:1]
        with pytest.raises(ValidationError, match="at least"):
            validate_lesson(lesson, "vocab")

    def test_item_missing_a_required_key_is_rejected(self):
        lesson = fallbacks.pick("vocab")
        lesson["items"] = copy.deepcopy(lesson["items"])
        lesson["items"][0]["advanced"] = ""
        with pytest.raises(ValidationError, match="advanced"):
            validate_lesson(lesson, "vocab")

    @pytest.mark.parametrize("field", ["question", "correct_option", "explanation"])
    def test_quiz_requires_its_fields(self, field):
        lesson = fallbacks.pick("quiz")
        lesson[field] = ""
        with pytest.raises(ValidationError):
            validate_lesson(lesson, "quiz")

    def test_quiz_needs_multiple_options(self):
        lesson = fallbacks.pick("quiz")
        lesson["options"] = ["A) only"]
        with pytest.raises(ValidationError, match="options"):
            validate_lesson(lesson, "quiz")


class TestPrompts:
    @pytest.mark.parametrize("format_key", ALL_FORMATS)
    def test_every_format_has_instructions(self, format_key):
        assert format_instructions(format_key).strip()

    def test_prompt_includes_recent_topics_to_avoid(self):
        prompt = build_prompt("vocab", ["Stop Saying Very Busy"])
        assert "Stop Saying Very Busy" in prompt

    def test_prompt_forbids_model_written_hashtags(self):
        # hashtags.py owns tags so they can rotate; the model must not add its own.
        assert "WITHOUT hashtags" in build_prompt("vocab", [])


class TestSendCTA:
    """DM sends are the heaviest-weighted reel signal; every lesson must ask."""

    @pytest.mark.parametrize("format_key", ALL_FORMATS)
    def test_every_format_produces_a_send_cta(self, format_key):
        assert fallbacks.pick(format_key)["send_cta"].strip()

    @pytest.mark.parametrize("format_key", ALL_FORMATS)
    def test_send_cta_names_a_person_not_a_vague_share(self, format_key):
        cta = fallbacks.pick(format_key)["send_cta"].lower()
        assert "send this to" in cta
        assert "share this with your friends" not in cta

    def test_send_cta_is_short_enough_to_render(self):
        for format_key in ALL_FORMATS:
            assert len(fallbacks.pick(format_key)["send_cta"].split()) <= 14

    def test_vocab_cta_references_the_actual_phrase(self):
        lesson = fallbacks.pick("vocab")
        basic = lesson["items"][0]["basic"]
        assert basic.lower() in lesson["send_cta"].lower()

    def test_prompt_requires_a_send_cta(self):
        assert "send_cta" in build_prompt("vocab", [])

    def test_caption_carries_the_send_cta(self):
        from reelbot.pipeline import _build_caption

        lesson = fallbacks.pick("vocab")
        assert lesson["send_cta"] in _build_caption(lesson, "vocab")

    def test_caption_does_not_duplicate_an_existing_cta(self):
        from reelbot.pipeline import _build_caption

        lesson = fallbacks.pick("vocab")
        lesson["caption"] = f"Body text\n\n{lesson['send_cta']}"
        assert _build_caption(lesson, "vocab").lower().count("send this to") == 1


class TestHashtagCount:
    def test_every_post_gets_a_full_set(self, tmp_path, monkeypatch):
        """A pool overlap used to leave a post short of the target.

        Hashtags categorise rather than distribute, but a set of five gave the
        classifier almost nothing to place the post with.
        """
        from reelbot.content import hashtags

        monkeypatch.setattr(hashtags, "HASHTAG_FILE", tmp_path / "h.json")
        for format_key in ALL_FORMATS:
            tags = hashtags.build_hashtags(format_key)
            assert len(tags) == hashtags.TAG_TARGET == 15, format_key

    def test_a_set_never_repeats_a_tag(self, tmp_path, monkeypatch):
        """Instagram counts a duplicated tag once; it is a wasted slot."""
        from reelbot.content import hashtags

        monkeypatch.setattr(hashtags, "HASHTAG_FILE", tmp_path / "h.json")
        for format_key in ALL_FORMATS:
            tags = hashtags.build_hashtags(format_key)
            assert len(set(tags)) == len(tags), format_key

    def test_consecutive_posts_do_not_share_the_whole_block(self, tmp_path, monkeypatch):
        """An identical block every day is the easiest automation fingerprint."""
        from reelbot.content import hashtags

        monkeypatch.setattr(hashtags, "HASHTAG_FILE", tmp_path / "h.json")
        sets = [tuple(hashtags.build_hashtags("vocab")) for _ in range(5)]
        assert len(set(sets)) > 1, "the rotation is not rotating"

    def test_pools_are_deep_enough_to_rotate(self):
        """Drawing N tags from a pool of N is not a rotation."""
        from reelbot.content import hashtags
        from reelbot.formats import get_spec

        assert len(hashtags.BROAD) >= hashtags.BROAD_PER_POST * 3
        assert len(hashtags.NICHE) >= hashtags.NICHE_PER_POST * 3
        for format_key in ALL_FORMATS:
            topic = get_spec(format_key).topic_tags
            assert len(topic) >= hashtags.TOPIC_PER_POST * 2, format_key


class TestCardCaption:
    """The card image has room for five swaps but not for example sentences,
    so the examples live in the caption - that is the format's teaching value."""

    def _caption(self):
        from reelbot.content.captions import build_caption

        return build_caption(fallbacks.pick("card"), "card")

    def test_every_alternative_appears(self):
        lesson = fallbacks.pick("card")
        from reelbot.content.captions import build_caption

        caption = build_caption(lesson, "card")
        for item in lesson["items"]:
            assert item["right"] in caption

    def test_every_example_appears(self):
        lesson = fallbacks.pick("card")
        from reelbot.content.captions import build_caption

        caption = build_caption(lesson, "card")
        for item in lesson["items"]:
            assert item["example"] in caption, f"missing example for {item['right']}"

    def test_alternatives_are_not_listed_twice(self):
        """The body is a hook only; the list is appended from `items`.

        Checked against the body rather than the assembled caption: an example
        sentence legitimately contains the phrase it demonstrates, so counting
        occurrences across the whole caption fails on correct content.
        """
        for lesson in fallbacks._lessons()["card"]:
            body = lesson.get("caption", "")
            for item in lesson["items"]:
                assert item["right"] not in body, (
                    f"{item['right']} is in the curated body of {lesson['title']!r} - "
                    "it would then appear twice once the block is appended"
                )

    def test_each_alternative_is_listed_once_in_the_appended_block(self):
        """The block itself must not repeat a swap."""
        from reelbot.content.captions import card_examples_block

        for lesson in fallbacks._lessons()["card"]:
            headers = [
                line for line in card_examples_block(lesson).splitlines()
                if " — " in line
            ]
            assert len(headers) == len(lesson["items"]), lesson["title"]

    def test_curated_card_captions_carry_no_example_sentences(self):
        """Contract: the model (and the fallbacks) write the hook, not the list."""
        for lesson in fallbacks._lessons()["card"]:
            for item in lesson["items"]:
                assert item["example"] not in lesson.get("caption", "")

    def test_block_is_empty_without_examples(self):
        from reelbot.content.captions import card_examples_block

        stripped = {"items": [{"wrong": "Very good", "right": "Excellent", "emoji": "⭐"}]}
        assert card_examples_block(stripped) == ""

    def test_other_formats_get_no_examples_block(self):
        """Only cards get the appended list; narrated formats show examples
        on screen, so repeating them would bloat the caption."""
        from reelbot.content.captions import build_caption, card_examples_block

        lesson = fallbacks.pick("vocab")
        caption = build_caption(lesson, "vocab")
        expected = f"{lesson['caption'].strip()}\n\n{SEND_PREFIX} {lesson['send_cta']}"
        assert caption == expected
        assert not card_examples_block(lesson), (
            "vocab items have no 'right'/'wrong' keys, so the card block must be empty"
        )

    @pytest.mark.parametrize("field", ["wrong", "right", "example"])
    def test_card_validation_requires_the_field(self, field):
        import copy as _copy

        lesson = fallbacks.pick("card")
        lesson["items"] = _copy.deepcopy(lesson["items"])
        lesson["items"][0][field] = ""
        with pytest.raises(ValidationError, match=field):
            validate_lesson(lesson, "card")

    def test_card_prompt_asks_for_examples(self):
        prompt = format_instructions("card")
        assert "'example'" in prompt
        assert "caption" in prompt.lower()
