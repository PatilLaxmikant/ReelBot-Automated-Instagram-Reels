"""Calendar rotation, hashtag rotation and the review-queue state machine."""
from __future__ import annotations

from datetime import date

import pytest

from reelbot.formats import ALL_FORMATS
from reelbot.planner import calendar
from reelbot.publish import queue


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """Point every state file at a temp dir so tests never touch real data."""
    for module, attr, name in (
        (queue, "QUEUE_FILE", "queue.json"),
        (calendar, "CALENDAR_FILE", "calendar_log.json"),
        (calendar, "SCHEDULE_FILE", "schedule.json"),
    ):
        monkeypatch.setattr(module, attr, tmp_path / name)
    yield


def make_item(item_id: str = "vocab_1", **kwargs) -> queue.QueueItem:
    defaults = dict(
        id=item_id, format="vocab", title="Test lesson",
        caption="caption", video_path="Reels/test.mp4",
    )
    defaults.update(kwargs)
    return queue.QueueItem(**defaults)


class TestRotation:
    def test_covers_every_format_within_two_weeks(self):
        """Sunday alternates, so the full cycle is 14 days rather than 7."""
        from datetime import timedelta

        start = date(2026, 8, 31)
        scheduled = {calendar.format_for(start + timedelta(days=i)) for i in range(14)}
        assert scheduled == set(ALL_FORMATS), (
            f"formats never scheduled: {set(ALL_FORMATS) - scheduled}"
        )

    def test_quiz_runs_three_times_a_week(self):
        """The account's own numbers put quizzes in 3 of its top 4 reels."""
        from datetime import timedelta

        start = date(2026, 8, 31)
        week = [calendar.format_for(start + timedelta(days=i)) for i in range(7)]
        assert week.count("quiz") == 3

    def test_has_all_seven_days(self):
        assert set(calendar.DEFAULT_ROTATION) == set(calendar.WEEKDAY_NAMES)

    def test_format_is_stable_for_a_given_weekday(self):
        monday = date(2026, 8, 31)
        assert monday.weekday() == 0
        assert calendar.format_for(monday) == calendar.DEFAULT_ROTATION["monday"]

    def test_sunday_alternates_between_weeks(self):
        from datetime import timedelta

        first = date(2026, 9, 6)
        assert first.weekday() == 6
        assert calendar.format_for(first) != calendar.format_for(first + timedelta(days=7))

    def test_upcoming_returns_requested_span(self):
        upcoming = calendar.upcoming(7, start=date(2026, 8, 31))
        assert len(upcoming) == 7
        assert [f for _, f in upcoming[:6]] == [
            calendar.DEFAULT_ROTATION[d] for d in calendar.WEEKDAY_NAMES[:6]
        ]

    def test_invalid_override_is_ignored(self):
        calendar.save_rotation({"monday": "not_a_format", "tuesday": "card"})
        rotation = calendar.load_rotation()
        assert rotation["monday"] == calendar.DEFAULT_ROTATION["monday"]
        assert rotation["tuesday"] == "card"


class TestRunLog:
    def test_already_ran_detects_same_day(self):
        day = date(2026, 8, 31)
        assert calendar.already_ran(day) is None
        calendar.record_run(day, "vocab", "Title", "vocab_1")
        assert calendar.already_ran(day)["format"] == "vocab"

    def test_other_days_are_unaffected(self):
        calendar.record_run(date(2026, 8, 31), "vocab", "Title", "vocab_1")
        assert calendar.already_ran(date(2026, 9, 1)) is None


class TestQueue:
    def test_add_then_find(self):
        queue.add(make_item())
        assert queue.find("vocab_1").status == queue.PENDING

    def test_new_items_are_pending_not_published(self):
        """The review gate: nothing reaches Instagram without approval."""
        queue.add(make_item())
        assert queue.by_status(*queue.PUBLISHABLE) == []

    def test_approve_moves_to_publishable(self):
        queue.add(make_item())
        queue.approve("vocab_1")
        assert [i.id for i in queue.by_status(*queue.PUBLISHABLE)] == ["vocab_1"]

    def test_reject_is_not_publishable(self):
        queue.add(make_item())
        queue.reject("vocab_1")
        assert queue.by_status(*queue.PUBLISHABLE) == []

    def test_cannot_approve_unknown_id(self):
        with pytest.raises(queue.QueueError):
            queue.approve("nope")

    def test_cannot_reject_a_published_item(self):
        queue.add(make_item())
        queue.set_status("vocab_1", queue.PUBLISHED)
        with pytest.raises(queue.QueueError):
            queue.reject("vocab_1")

    def test_publishing_stamps_a_timestamp(self):
        queue.add(make_item())
        assert queue.set_status("vocab_1", queue.PUBLISHED).published_at

    def test_failure_records_the_error(self):
        queue.add(make_item())
        item = queue.set_status("vocab_1", queue.FAILED, error="login blocked")
        assert item.status == queue.FAILED and item.error == "login blocked"

    def test_approve_all_only_touches_pending(self):
        queue.add(make_item("a"))
        queue.add(make_item("b"))
        queue.add(make_item("c"))
        queue.reject("c")
        assert {i.id for i in queue.approve_all()} == {"a", "b"}

    def test_roundtrip_preserves_fields(self):
        queue.add(make_item(duration_sec=31.5, thumbnail_path="Reels/t.jpg"))
        item = queue.find("vocab_1")
        assert item.duration_sec == 31.5
        assert item.thumbnail_path == "Reels/t.jpg"


class TestHashtags:
    def test_rotation_varies_between_posts(self, tmp_path, monkeypatch):
        from reelbot.content import hashtags

        monkeypatch.setattr(hashtags, "HASHTAG_FILE", tmp_path / "hashtags.json")
        first = set(hashtags.build_hashtags("vocab"))
        second = set(hashtags.build_hashtags("vocab"))
        assert first != second, "consecutive posts must not reuse the same tag block"
        assert set(hashtags.CORE) <= first & second, "core tags must always be present"

    def test_model_hashtags_are_replaced_not_appended(self, tmp_path, monkeypatch):
        from reelbot.content import hashtags

        monkeypatch.setattr(hashtags, "HASHTAG_FILE", tmp_path / "hashtags.json")
        result = hashtags.apply_hashtags("Body text\n\n#old #stale", "vocab")
        assert "#old" not in result and "#stale" not in result
        assert "Body text" in result

    def test_within_instagram_limit(self, tmp_path, monkeypatch):
        from reelbot.content import hashtags

        monkeypatch.setattr(hashtags, "HASHTAG_FILE", tmp_path / "hashtags.json")
        for format_key in ALL_FORMATS:
            assert len(hashtags.build_hashtags(format_key)) <= 30
