"""Hook-pattern classification and cooldown.

The account's real catalogue was 59% ``Stop Saying ___`` and 44% the single
shape ``Stop Saying "Very ___"``. Topic history already stopped exact repeats;
these tests cover the layer that stops the *shape* repeating.
"""
from __future__ import annotations

import pytest

from reelbot.content import hooks
from reelbot.content.prompts import build_prompt


class TestClassification:
    @pytest.mark.parametrize(
        "title, family",
        [
            ('Stop Saying "Very Busy"', "stop-saying-very"),
            ("Stop Saying 'very cold'", "stop-saying-very"),
            ('Stop Saying "Nice"', "stop-saying"),
            ("Stop Confusing These Two Words!", "stop-confusing"),
            ("95% Fail This Tricky Test!", "percent-hype"),
            ("Only 5% Get This Right!", "percent-hype"),
            ("Textbook English vs Native English", "textbook-vs-native"),
            ("Quick English Challenge!", "challenge"),
            ("How to Sound Professional at Work", "how-to-sound"),
            ("Don't Say This In A Meeting", "dont-say"),
        ],
    )
    def test_known_shapes(self, title, family):
        assert hooks.hook_family(title) == family

    def test_very_is_matched_before_the_general_case(self):
        """Order matters: the narrow pattern has to win."""
        assert hooks.hook_family('Stop Saying "Very Tired"') == "stop-saying-very"

    @pytest.mark.parametrize("title", ["", "   ", None])
    def test_empty_titles_are_other(self, title):
        assert hooks.hook_family(title) == hooks.OTHER

    def test_unrecognised_shape_is_other(self):
        assert hooks.hook_family("Three words that changed my English") == hooks.OTHER


class TestCooldown:
    def test_recent_family_is_on_cooldown(self):
        history = ['Stop Saying "Very Busy"']
        assert hooks.is_on_cooldown('Stop Saying "Very Cold"', history)

    def test_a_different_shape_is_allowed(self):
        history = ['Stop Saying "Very Busy"']
        assert not hooks.is_on_cooldown("Quick English Challenge!", history)

    def test_cooldown_expires_outside_the_window(self):
        history = ['Stop Saying "Very Busy"'] + [f"Unique lesson {i}" for i in range(6)]
        assert not hooks.is_on_cooldown('Stop Saying "Very Cold"', history)

    def test_other_never_blocks(self):
        """`other` is a catch-all, not a pattern worth banning."""
        history = ["Three words that changed my English"]
        assert not hooks.is_on_cooldown("Something else entirely", history)

    def test_recent_families_are_deduplicated(self):
        history = ['Stop Saying "Very A"', 'Stop Saying "Very B"', 'Stop Saying "Very C"']
        assert hooks.recent_families(history) == ["stop-saying-very"]

    def test_empty_history_bans_nothing(self):
        assert hooks.recent_families([]) == []
        assert hooks.avoid_clause([]) == ""


class TestPromptIntegration:
    def test_ban_clause_names_the_banned_shape(self):
        clause = hooks.avoid_clause(['Stop Saying "Very Busy"'])
        assert "BANNED" in clause
        assert 'Stop Saying "Very ___"' in clause

    def test_ban_clause_offers_alternatives(self):
        clause = hooks.avoid_clause(['Stop Saying "Very Busy"'])
        assert any(shape[:20] in clause for shape in hooks.ALTERNATIVE_HOOKS)

    def test_prompt_carries_the_ban(self):
        clause = hooks.avoid_clause(['Stop Saying "Very Busy"'])
        assert "BANNED" in build_prompt("vocab", [], hook_ban=clause)

    def test_retry_prompt_escalates(self):
        plain = build_prompt("vocab", [], hook_ban="x")
        insisted = build_prompt("vocab", [], hook_ban="x", insist=True)
        assert "PREVIOUS ATTEMPT" in insisted
        assert "PREVIOUS ATTEMPT" not in plain

    def test_vocab_prompt_no_longer_only_offers_very(self):
        """The topic pool was ten 'Very ___' phrases and nothing else."""
        from reelbot.content.prompts import format_instructions

        prompt = format_instructions("vocab")
        assert "ROTATE ACROSS THESE CATEGORIES" in prompt
        for category in ("Weak verbs", "Filler openers", "Flat adjectives"):
            assert category in prompt


class TestAgainstRealCatalogue:
    """The shapes actually present in this account's published history."""

    CATALOGUE = [
        'Stop Saying "Very Sad"', "Quick English Challenge!",
        "Textbook English vs Native English", "Stop Confusing These Two Words!",
        'Stop Saying "Very important"', 'Stop Saying "Very Angry"',
        "95% Fail This Tricky Test!", "How to Sound Professional at Work",
    ]

    def test_dominant_shape_is_detected(self):
        families = [hooks.hook_family(t) for t in self.CATALOGUE]
        assert families.count("stop-saying-very") == 3

    def test_a_run_of_the_same_shape_gets_banned(self):
        run = ['Stop Saying "Very A"', 'Stop Saying "Very B"', 'Stop Saying "Very C"']
        assert "stop-saying-very" in hooks.recent_families(run)
        assert hooks.is_on_cooldown('Stop Saying "Very D"', run)


class TestGeneratorRetry:
    """The prompt asks; the retry enforces. Mocked - no network."""

    @staticmethod
    def _fake_client(monkeypatch, titles):
        """Return a genai.Client stub yielding `titles` in order, and a call log.

        Each stub lesson teaches the subject its own title announces. A stub
        whose items said "very busy" under a title about "very cold" would trip
        the topic-repeat guard, and these tests are about hook shape.
        """
        import json as _json

        from google import genai

        from reelbot.store.history import subject

        calls: list[str] = []
        remaining = list(titles)

        class Response:
            def __init__(self, text): self.text = text

        class Models:
            def generate_content(self, *, model, contents, config):
                calls.append(contents)
                title = remaining.pop(0) if remaining else remaining_last[0]
                topic = subject(title)
                return Response(_json.dumps({
                    "title": title,
                    "items": [
                        {"basic": topic, "advanced": "swamped", "example": "I'm swamped."},
                        {"basic": topic, "advanced": "tied up", "example": "I'm tied up."},
                    ],
                    "caption": "body",
                }))

        remaining_last = [titles[-1]]

        class Client:
            def __init__(self, *a, **k): self.models = Models()

        monkeypatch.setattr(genai, "Client", Client)
        return calls

    @pytest.fixture(autouse=True)
    def _with_key(self, monkeypatch):
        """Real settings with an API key swapped in.

        Derived via ``dataclasses.replace`` rather than constructed field by
        field, so adding a setting cannot break this test.
        """
        import dataclasses

        from reelbot.settings import get_settings

        fake = dataclasses.replace(get_settings(), gemini_api_key="test-key", gemini_model="m")
        monkeypatch.setattr("reelbot.content.generator.get_settings", lambda: fake)

    def test_retries_when_the_model_reuses_a_banned_hook(self, monkeypatch):
        from reelbot.content.generator import generate_lesson

        history = ['Stop Saying "Very Busy"']
        calls = self._fake_client(
            monkeypatch, ['Stop Saying "Very Cold"', "Three phrases that sound natural"]
        )
        lesson = generate_lesson("vocab", history=history)

        assert len(calls) == 2, "a banned hook should trigger exactly one retry"
        assert "PREVIOUS ATTEMPT" in calls[1], "the retry prompt should escalate"
        assert lesson["title"] == "Three phrases that sound natural"

    def test_no_retry_when_the_hook_is_fresh(self, monkeypatch):
        from reelbot.content.generator import generate_lesson

        history = ['Stop Saying "Very Busy"']
        calls = self._fake_client(monkeypatch, ["Three phrases that sound natural"])
        lesson = generate_lesson("vocab", history=history)

        assert len(calls) == 1, "a fresh hook must not cost a second API call"
        assert lesson["title"] == "Three phrases that sound natural"

    def test_keeps_the_lesson_if_the_retry_also_repeats(self, monkeypatch):
        """A repeated hook still beats falling back to an already-posted lesson."""
        from reelbot.content.generator import generate_lesson

        history = ['Stop Saying "Very Busy"']
        calls = self._fake_client(
            monkeypatch, ['Stop Saying "Very Cold"', 'Stop Saying "Very Warm"']
        )
        lesson = generate_lesson("vocab", history=history)

        assert len(calls) == 2, "it must not retry forever"
        assert lesson["title"].startswith("Stop Saying")

    def test_no_ban_clause_means_no_retry_path(self, monkeypatch):
        from reelbot.content.generator import generate_lesson

        calls = self._fake_client(monkeypatch, ['Stop Saying "Very Cold"'])
        generate_lesson("vocab", history=[])
        assert len(calls) == 1
        assert "BANNED" not in calls[0]
