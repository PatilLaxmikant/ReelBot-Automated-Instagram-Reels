"""Upload memory: what the account has already taught, and never teaching it twice.

The defect these guard against is visible in the account's own numbers. Over one
week it published ``Stop Saying "Very Busy"`` twice under two different
headlines - 165 views, then 170 - and four of the six formats had a curated
fallback pool of exactly one lesson, so every fallback was the same reel.
"""
from __future__ import annotations

import json

import pytest

from reelbot.content import fallbacks
from reelbot.formats import ALL_FORMATS
from reelbot.publish import queue, sync
from reelbot.store import history


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """Point every state file at a temp dir so tests never touch real data."""
    monkeypatch.setattr(history, "HISTORY_FILE", tmp_path / "lesson_history.json")
    monkeypatch.setattr(queue, "QUEUE_FILE", tmp_path / "queue.json")
    monkeypatch.setattr(sync, "PUBLISHED_FILE", tmp_path / "published.json")
    yield


def publish(*posts: tuple[str, str]) -> None:
    """Record ``(queue_id, caption_head)`` pairs as live on the account."""
    sync.save([sync.PublishedPost(pk=str(i), queue_id=qid, caption_head=head)
               for i, (qid, head) in enumerate(posts)])


class TestSubject:
    """Two titles for one lesson have to reduce to the same key."""

    @pytest.mark.parametrize(
        "title",
        [
            'Stop Saying "Very Busy"',
            "Stop saying 'Very Busy'! Want to sound instantly more natural?",
            "❌ Stop Saying Very Busy 🤯",
            "Never say very busy",
        ],
    )
    def test_one_lesson_has_one_key(self, title):
        assert history.subject(title) == "busy"

    def test_different_lessons_keep_different_keys(self):
        keys = {history.subject(t) for t in (
            'Stop Saying "Very Busy"',
            'Stop Saying "Very Cold"',
            "Textbook English vs Native English",
            "How to Sound Professional at Work",
        )}
        assert len(keys) == 4

    def test_empty_input_has_no_key(self):
        assert history.subject("") == ""
        assert history.subject(None) == ""

    def test_a_caption_reduces_to_its_hook(self):
        """Published posts are remembered by caption, which runs on past the hook."""
        caption = 'Stop saying "Very easy"! Unlock natural English with these three swaps'
        assert history.subject(caption) == "easy"


class TestLessonKeys:
    def test_a_quiz_is_identified_by_its_question(self):
        """Quiz titles are interchangeable hype; the question is the lesson."""
        keys = history.lesson_keys({
            "title": "95% Fail This Quiz!",
            "question": "I look forward _ from you.",
        })
        assert any("look forward" in key for key in keys)

    def test_item_subjects_are_recorded(self):
        keys = history.lesson_keys({
            "title": "Three Upgrades",
            "items": [{"basic": "Very cold"}, {"basic": "Very cold"}],
        })
        assert "cold" in keys


class TestIsRepeat:
    def test_a_covered_topic_under_a_new_title_is_a_repeat(self):
        history.remember('Stop Saying "Very Busy"')
        assert history.is_repeat("Never say very busy again!")

    def test_a_new_topic_is_not_a_repeat(self):
        history.remember('Stop Saying "Very Busy"')
        assert not history.is_repeat("Better Ways to Say 'Confused'")

    def test_an_empty_memory_repeats_nothing(self):
        assert not history.is_repeat("Anything at all")

    def test_one_shared_item_is_not_enough(self):
        """Vocabulary lessons legitimately reuse a word; rejecting on one
        overlap would reject almost every lesson."""
        history.remember("Upgrade 'Nice'", {"items": [{"basic": "Nice"}]})
        assert not history.is_repeat({
            "title": "Words for a Good Impression",
            "items": [{"basic": "Nice"}, {"basic": "Boring"}],
        })

    def test_a_wholly_recycled_lesson_is_a_repeat(self):
        history.remember("Upgrade 'Nice'", {"items": [{"basic": "Nice"}, {"basic": "Boring"}]})
        assert history.is_repeat({
            "title": "A Completely Different Headline",
            "items": [{"basic": "Nice"}, {"basic": "Boring"}],
        })

    def test_a_topic_posted_by_hand_still_counts(self):
        """The bot's own log cannot see posts made from the phone."""
        publish(("", 'Stop saying "Very Busy"! Sound natural instead'))
        assert history.is_repeat("Never say very busy")

    def test_a_queued_but_unpublished_topic_still_counts(self):
        """Two pending reels on the same topic is the same waste."""
        queue.add(queue.QueueItem(
            id="vocab_1", format="vocab", title='Stop Saying "Very Busy"',
            caption="c", video_path="v.mp4",
        ))
        assert history.is_repeat("Never say very busy")


class TestStorage:
    def test_legacy_string_entries_still_load(self, tmp_path):
        """History was a plain list of titles; existing files must keep working."""
        history.HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        history.HISTORY_FILE.write_text(json.dumps(["Old Title"]), encoding="utf-8")
        assert history.load_history() == ["Old Title"]
        assert history.is_repeat("Old Title")

    def test_remember_stores_the_content_keys(self):
        history.remember("A Title", {"items": [{"basic": "Very cold"}]})
        assert "cold" in history.load_entries()[0]["keys"]

    def test_remember_moves_a_repeat_to_the_end(self):
        for title in ("First", "Second"):
            history.remember(title)
        history.remember("First")
        assert history.load_history() == ["Second", "First"]

    def test_blank_titles_are_not_stored(self):
        history.remember("   ")
        assert history.load_history() == []

    def test_history_is_capped(self, monkeypatch):
        monkeypatch.setattr(history, "MAX_ENTRIES", 3)
        for index in range(6):
            history.remember(f"Lesson {index}")
        assert len(history.load_history()) == 3

    def test_used_titles_merges_all_three_sources(self):
        history.remember("From the local log")
        queue.add(queue.QueueItem(id="q1", format="vocab", title="From the queue",
                                  caption="c", video_path="v.mp4"))
        publish(("", "From Instagram"))
        assert set(history.used_titles()) == {
            "From the local log", "From the queue", "From Instagram"
        }

    def test_used_titles_does_not_repeat_one_post(self):
        """A published post is also in the queue; it must be listed once."""
        queue.add(queue.QueueItem(id="q1", format="vocab", title="Shared Lesson",
                                  caption="c", video_path="v.mp4"))
        publish(("q1", "some caption text"))
        assert history.used_titles().count("Shared Lesson") == 1

    def test_missing_state_files_are_not_fatal(self):
        """A fresh checkout has no published.json and no queue."""
        assert history.used_titles() == []
        assert history.used_keys() == set()


class TestFallbackVariety:
    """The complaint: 'the fallback is single each time, it gives the same'."""

    @pytest.mark.parametrize("format_key", ALL_FORMATS)
    def test_every_format_has_a_real_pool(self, format_key):
        assert fallbacks.pool_size(format_key) >= 8, (
            f"{format_key} has {fallbacks.pool_size(format_key)} curated lessons - "
            "a pool this small repeats as soon as the API is unavailable twice"
        )

    @pytest.mark.parametrize("format_key", ALL_FORMATS)
    def test_the_pool_is_exhausted_before_anything_repeats(self, format_key):
        """Random selection over a pool of one is why every fallback was identical."""
        used: list[str] = []
        for _ in range(fallbacks.pool_size(format_key)):
            used.append(fallbacks.pick(format_key, used)["title"])
        assert len(set(used)) == fallbacks.pool_size(format_key), (
            f"{format_key} repeated a lesson before its pool ran out: {used}"
        )

    def test_the_least_recently_used_lesson_comes_back_first(self):
        pool = [lesson["title"] for lesson in fallbacks._lessons()["vocab"]]
        # Everything used, oldest first.
        assert fallbacks.pick("vocab", pool)["title"] == pool[0]

    def test_a_topic_covered_under_another_title_is_not_offered(self):
        """The account posted 'Very Busy'; the curated lesson on it is spent."""
        chosen = fallbacks.pick("vocab", ["Never say very busy at work"])
        assert history.subject(chosen["title"]) != "busy"

    def test_the_pool_is_consulted_even_with_no_history_argument(self):
        history.remember("Say This Instead of 'Boring'")
        assert fallbacks.pick("vocab")["title"] != "Say This Instead of 'Boring'"

    @pytest.mark.parametrize("format_key", ALL_FORMATS)
    def test_every_curated_lesson_is_a_distinct_topic(self, format_key):
        subjects = [history.subject(lesson["title"])
                    for lesson in fallbacks._lessons()[format_key]]
        assert len(set(subjects)) == len(subjects), (
            f"{format_key} lists the same topic twice: {subjects}"
        )


class TestGeneratorRefusesCoveredTopics:
    """The model is asked not to repeat; this is what happens when it does."""

    @staticmethod
    def _stub(monkeypatch, lessons):
        """Serve ``lessons`` in order from a fake genai client. Returns a call log."""
        import dataclasses

        from google import genai

        from reelbot.settings import get_settings

        fake = dataclasses.replace(get_settings(), gemini_api_key="k", gemini_model="m")
        monkeypatch.setattr("reelbot.content.generator.get_settings", lambda: fake)

        calls: list[str] = []
        remaining = list(lessons)

        class Models:
            def generate_content(self, *, model, contents, config):
                calls.append(contents)
                payload = remaining.pop(0) if remaining else lessons[-1]
                return type("R", (), {"text": json.dumps(payload)})()

        monkeypatch.setattr(
            genai, "Client", type("C", (), {
                "__init__": lambda self, *a, **k: setattr(self, "models", Models()),
            })
        )
        return calls

    @staticmethod
    def _lesson(title, basic):
        return {
            "title": title,
            "items": [
                {"basic": basic, "advanced": "swamped", "example": "I'm swamped."},
                {"basic": basic, "advanced": "tied up", "example": "I'm tied up."},
            ],
            "caption": "body",
        }

    def test_a_covered_topic_is_regenerated(self, monkeypatch):
        from reelbot.content.generator import generate_lesson

        calls = self._stub(monkeypatch, [
            self._lesson("A Fresh Headline For An Old Lesson", "Very busy"),
            self._lesson("Better Ways to Say Confused", "Confused"),
        ])
        lesson = generate_lesson("vocab", history=['Stop Saying "Very Busy"'])

        assert len(calls) == 2, "a covered topic must trigger exactly one retry"
        assert lesson["title"] == "Better Ways to Say Confused"

    def test_the_ban_list_reaches_the_prompt(self, monkeypatch):
        from reelbot.content.generator import generate_lesson

        calls = self._stub(monkeypatch, [self._lesson("Something New", "Confused")])
        generate_lesson("vocab", history=['Stop Saying "Very Busy"'])

        assert "TOPIC BAN" in calls[0]
        assert "busy" in calls[0]

    def test_two_covered_topics_fall_back_to_the_curated_pool(self, monkeypatch):
        """Posting a third 'Very Busy' reel is worse than posting a curated one."""
        from reelbot.content.generator import generate_lesson

        calls = self._stub(monkeypatch, [
            self._lesson("One Headline", "Very busy"),
            self._lesson("Another Headline", "Very busy"),
        ])
        lesson = generate_lesson("vocab", history=['Stop Saying "Very Busy"'])

        assert len(calls) == 2, "it must not retry forever"
        assert not history.is_repeat(lesson, {"busy"}), (
            f"{lesson['title']!r} still teaches a topic the account has covered"
        )

    def test_a_fresh_topic_costs_one_call(self, monkeypatch):
        from reelbot.content.generator import generate_lesson

        calls = self._stub(monkeypatch, [self._lesson("Say This Instead of Boring", "Boring")])
        lesson = generate_lesson("vocab", history=['Stop Saying "Very Busy"'])

        assert len(calls) == 1, "a fresh topic must not cost a second API call"
        assert lesson["title"] == "Say This Instead of Boring"


class TestTopicIsFoundAnywhereInTheTitle:
    """A subject the title mentions late used to escape the memory entirely.

    ``Three Better Words Than Very Happy`` teaches the same lesson as
    ``Stop Saying "Very Happy"`` - which this account posted - but only the
    second opens with the topic.
    """

    @pytest.mark.parametrize("title", [
        'Stop Saying "Very Happy"',
        "Three Better Words Than Very Happy",
        "Sound natural: drop very happy from your vocabulary",
    ])
    def test_the_topic_is_found_wherever_it_sits(self, title):
        assert history.subject(title) == "happy"

    def test_a_late_topic_is_still_caught_as_a_repeat(self):
        history.remember('Stop Saying "Very Happy"')
        assert history.is_repeat("Three Better Words Than Very Happy")

    def test_instead_of_names_the_topic(self):
        assert history.subject("Say This Instead of Boring") == "boring"

    def test_a_common_verb_does_not_become_the_topic(self):
        """A bare 'say ___' rule collapsed every 'What to Say When ...' lesson
        onto the single subject 'when'."""
        first = history.subject("What to Say When You Miss a Deadline")
        second = history.subject("What to Write When You Need an Update")
        assert first != second
        assert not history.matches(first, second)


class TestPipelineUsesTheWholeMemory:
    def test_the_generator_is_not_handed_a_narrowed_history(self):
        """The pipeline must not pass titles: per-item subject keys are stored
        with each past lesson, and a list of titles silently drops them."""
        import inspect

        from reelbot import pipeline

        source = inspect.getsource(pipeline.generate_reel)
        assert "generate_lesson(format_key)" in source, (
            "passing a history list narrows the memory to what a headline reveals"
        )

    def test_item_keys_survive_into_the_generator_view(self):
        """A lesson whose title hides its subject is still remembered by item."""
        history.remember("A Vague Headline", {"items": [{"basic": "Very cold"}]})
        assert "cold" in history.used_keys()
        assert "cold" not in {history.subject(t) for t in history.used_titles()}


class TestAccountMemoryRefresh:
    """The live half of the memory is only as fresh as the last sync."""

    def _settings(self, has_instagram: bool):
        return type("S", (), {"has_instagram": has_instagram, "auto_publish": False})()

    def test_a_daily_run_refreshes_before_generating(self, monkeypatch):
        """Generating first would use a stale view of the account."""
        from reelbot.planner import runner

        order: list[str] = []
        monkeypatch.setattr(runner, "get_settings", lambda: self._settings(True))
        monkeypatch.setattr("reelbot.publish.sync.sync",
                            lambda *a, **k: order.append("sync") or sync.SyncResult())
        monkeypatch.setattr(runner.calendar, "already_ran", lambda *a, **k: None)
        monkeypatch.setattr(runner.calendar, "record_run", lambda *a, **k: None)
        monkeypatch.setattr(runner, "generate_reel",
                            lambda **k: order.append("generate") or _FakeResult())

        runner.run_daily()
        assert order == ["sync", "generate"]

    def test_an_unreachable_account_does_not_stop_the_run(self, monkeypatch):
        """Task Scheduler runs this unattended; a network blip must not fail it."""
        from reelbot.planner import runner

        monkeypatch.setattr(runner, "get_settings", lambda: self._settings(True))
        monkeypatch.setattr(
            "reelbot.publish.sync.sync",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("login failed")),
        )
        assert runner._refresh_account_memory() is False

    def test_no_credentials_means_no_call(self, monkeypatch):
        from reelbot.planner import runner

        monkeypatch.setattr(runner, "get_settings", lambda: self._settings(False))
        monkeypatch.setattr(
            "reelbot.publish.sync.sync",
            lambda *a, **k: pytest.fail("sync must not be attempted without credentials"),
        )
        assert runner._refresh_account_memory() is False


class _FakeResult:
    item = type("I", (), {"id": "x", "title": "T", "format": "vocab"})()
