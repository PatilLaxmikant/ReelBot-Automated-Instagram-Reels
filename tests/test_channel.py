"""Instagram history sync and grid retention.

Retention is the only part of this project that can destroy something
irrecoverably, so most of these tests are about the gates rather than the happy
path: dry run by default, archive by default, and delete refused unless
confirmed explicitly.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from reelbot.publish import retention, sync
from reelbot.publish.sync import PublishedPost

NOW = datetime.now(timezone.utc).astimezone()


def post(pk: str, views: int, days: float = 30, **kw) -> PublishedPost:
    return PublishedPost(
        pk=pk, play_count=views,
        taken_at=(NOW - timedelta(days=days)).isoformat(timespec="seconds"),
        **kw,
    )


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(sync, "PUBLISHED_FILE", tmp_path / "published.json")
    monkeypatch.setattr(retention, "RETENTION_LOG", tmp_path / "retention.json")
    monkeypatch.setattr(retention, "PAUSE", (0.0, 0.0))  # no sleeping in tests
    yield


class FakeClient:
    """Records what it was asked to do; never touches the network."""

    def __init__(self, fail: set[str] | None = None):
        self.archived: list[str] = []
        self.deleted: list[str] = []
        self.fail = fail or set()

    def media_archive(self, pk):
        if pk in self.fail:
            raise RuntimeError("rate limited")
        self.archived.append(pk)
        return True

    def media_delete(self, pk):
        if pk in self.fail:
            raise RuntimeError("rate limited")
        self.deleted.append(pk)
        return True


class TestPlan:
    def test_keeps_the_best_n(self):
        posts = [post(str(i), views) for i, views in enumerate([500, 400, 300, 200, 100])]
        plan = retention.build_plan(keep=3, posts=posts)
        assert [p.play_count for p in plan.keep] == [500, 400, 300]
        assert [p.play_count for p in plan.retire] == [200, 100]

    def test_recent_posts_are_never_retired(self):
        """A reel earns its numbers over days; judging it early is wrong."""
        posts = [post("old", 900, days=40), post("new", 3, days=1)]
        plan = retention.build_plan(keep=1, posts=posts)
        assert "new" in {p.pk for p in plan.keep}
        assert plan.too_young and plan.too_young[0].pk == "new"

    def test_young_posts_consume_keep_slots(self):
        posts = [post(str(i), 100 - i, days=40) for i in range(5)] + [post("y", 1, days=1)]
        plan = retention.build_plan(keep=3, posts=posts)
        assert len(plan.keep) == 3
        assert "y" in {p.pk for p in plan.keep}

    def test_comments_break_ties_above_likes(self):
        a = post("a", 100, like_count=50, comment_count=0)
        b = post("b", 100, like_count=0, comment_count=5)
        ranked = sorted([a, b], key=lambda p: p.score, reverse=True)
        assert ranked[0].pk == "b"

    def test_nothing_to_do_when_under_the_limit(self):
        plan = retention.build_plan(keep=12, posts=[post("a", 10)])
        assert plan.is_noop

    @pytest.mark.parametrize("bad", [0, -1])
    def test_keep_must_be_positive(self, bad):
        with pytest.raises(retention.RetentionError):
            retention.build_plan(keep=bad, posts=[])

    def test_unknown_mode_is_rejected(self):
        with pytest.raises(retention.RetentionError, match="Unknown mode"):
            retention.build_plan(mode="nuke", posts=[])


class TestSafetyGates:
    """The part that matters. Each gate is tested for what it prevents."""

    def _plan(self, mode=retention.ARCHIVE):
        posts = [post(str(i), 100 - i) for i in range(5)]
        return retention.build_plan(keep=2, mode=mode, posts=posts)

    def test_dry_run_is_the_default(self):
        client = FakeClient()
        outcome = retention.apply_plan(self._plan(), client=client)
        assert outcome.applied is False
        assert not client.archived and not client.deleted

    def test_delete_refused_without_confirmation(self):
        client = FakeClient()
        with pytest.raises(retention.RetentionError, match="confirm_delete"):
            retention.apply_plan(
                self._plan(retention.DELETE), apply=True, client=client
            )
        assert not client.deleted, "nothing may be deleted when the gate refuses"

    def test_delete_requires_apply_too(self):
        """confirm_delete alone is not enough; apply is a separate gate."""
        client = FakeClient()
        outcome = retention.apply_plan(
            self._plan(retention.DELETE), confirm_delete=True, client=client
        )
        assert outcome.applied is False and not client.deleted

    def test_archive_never_deletes(self):
        client = FakeClient()
        retention.apply_plan(self._plan(), apply=True, client=client)
        assert client.archived and not client.deleted

    def test_delete_with_both_gates_proceeds(self):
        client = FakeClient()
        outcome = retention.apply_plan(
            self._plan(retention.DELETE), apply=True, confirm_delete=True, client=client
        )
        assert outcome.applied and client.deleted and not client.archived

    def test_one_failure_does_not_stop_the_batch(self):
        client = FakeClient(fail={"4"})
        outcome = retention.apply_plan(self._plan(), apply=True, client=client)
        assert len(outcome.succeeded) == 2
        assert [pk for pk, _ in outcome.failed] == ["4"]

    def test_every_run_is_logged(self):
        retention.apply_plan(self._plan(), client=FakeClient())
        entries = retention.history()
        assert entries and entries[-1]["mode"] == retention.ARCHIVE
        assert entries[-1]["applied"] is False


class TestArchiveIsReversible:
    def test_archived_posts_stay_on_record(self):
        posts = [post(str(i), 100 - i) for i in range(4)]
        sync.save(posts)
        plan = retention.build_plan(keep=2, posts=posts)
        retention.apply_plan(plan, apply=True, client=FakeClient())

        stored = {p.pk: p for p in sync.load()}
        assert len(stored) == 4, "archiving must not drop the record"
        assert sum(1 for p in stored.values() if p.archived) == 2

    def test_deleted_posts_are_dropped_from_record(self):
        posts = [post(str(i), 100 - i) for i in range(4)]
        sync.save(posts)
        plan = retention.build_plan(keep=2, mode=retention.DELETE, posts=posts)
        retention.apply_plan(plan, apply=True, confirm_delete=True, client=FakeClient())
        assert len(sync.load()) == 2

    def test_live_posts_excludes_archived(self):
        sync.save([post("a", 10), post("b", 20, archived=True)])
        assert [p.pk for p in sync.live_posts()] == ["a"]


class TestSyncStore:
    def test_round_trip(self):
        sync.save([post("a", 5, caption_head="hello")])
        loaded = sync.load()
        assert loaded[0].pk == "a" and loaded[0].caption_head == "hello"

    def test_url_built_from_code(self):
        assert PublishedPost(pk="1", code="ABC").url.endswith("/reel/ABC/")

    def test_missing_code_gives_no_url(self):
        assert PublishedPost(pk="1").url == ""

    def test_empty_store_is_empty(self):
        assert sync.load() == []
        assert sync.last_synced() == ""
