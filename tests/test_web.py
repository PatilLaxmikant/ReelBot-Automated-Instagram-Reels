"""Dashboard API.

The endpoints that can change the account are the ones worth testing: the
automation-mode switch, the settings allowlist, and the retention gates. Long
operations go to a worker thread, so the tests assert what was *submitted*
rather than waiting on the work itself.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from reelbot.publish import retention, sync
from reelbot.web import jobs
from reelbot.web.app import app


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Point every state file at a temp dir and reset the job runner."""
    from reelbot import settings as settings_mod
    from reelbot.planner import calendar
    from reelbot.publish import queue
    from reelbot.store import history

    monkeypatch.setattr(queue, "QUEUE_FILE", tmp_path / "queue.json")
    monkeypatch.setattr(calendar, "CALENDAR_FILE", tmp_path / "cal.json")
    monkeypatch.setattr(calendar, "SCHEDULE_FILE", tmp_path / "sched.json")
    monkeypatch.setattr(history, "HISTORY_FILE", tmp_path / "history.json")
    monkeypatch.setattr(sync, "PUBLISHED_FILE", tmp_path / "published.json")
    monkeypatch.setattr(retention, "RETENTION_LOG", tmp_path / "retention.json")
    monkeypatch.setattr(settings_mod, "SETTINGS_FILE", tmp_path / "settings.json")
    settings_mod.get_settings.cache_clear()
    jobs.runner.__init__()
    yield
    settings_mod.get_settings.cache_clear()


@pytest.fixture
def client():
    return TestClient(app)


class TestState:
    def test_state_is_served(self, client):
        body = client.get("/api/state").json()
        for key in ("settings", "today", "upcoming", "queue", "counts", "channel"):
            assert key in body

    def test_dashboard_page_renders(self, client):
        res = client.get("/")
        assert res.status_code == 200
        assert "ReelBot" in res.text

    def test_upcoming_covers_a_week(self, client):
        assert len(client.get("/api/state").json()["upcoming"]) == 7


class TestAutomationMode:
    def test_switching_to_full_automation(self, client):
        assert client.post("/api/settings", json={"key": "publish_mode",
                                                  "value": "auto"}).status_code == 200
        assert client.get("/api/state").json()["settings"]["publish_mode"] == "auto"

    def test_switching_back_to_semi(self, client):
        client.post("/api/settings", json={"key": "publish_mode", "value": "auto"})
        client.post("/api/settings", json={"key": "publish_mode", "value": "review"})
        assert client.get("/api/state").json()["settings"]["publish_mode"] == "review"

    def test_invalid_mode_rejected(self, client):
        res = client.post("/api/settings", json={"key": "publish_mode", "value": "yolo"})
        assert res.status_code == 400

    def test_story_toggle(self, client):
        client.post("/api/settings", json={"key": "share_to_story", "value": False})
        assert client.get("/api/state").json()["settings"]["share_to_story"] is False

    def test_credentials_cannot_be_changed_from_the_ui(self, client):
        """The UI must not be able to rewrite secrets."""
        for key in ("gemini_api_key", "instagram_password", "instagram_username"):
            res = client.post("/api/settings", json={"key": key, "value": "x"})
            assert res.status_code == 400


class TestRetentionEndpoint:
    def _seed(self):
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc).astimezone()
        sync.save([
            sync.PublishedPost(
                pk=str(i), play_count=100 - i,
                taken_at=(now - timedelta(days=30)).isoformat(timespec="seconds"),
            )
            for i in range(6)
        ])

    def test_preview_does_not_apply(self, client):
        self._seed()
        body = client.post("/api/retention",
                           json={"keep": 3, "mode": "archive", "apply": False}).json()
        assert body["applied"] is False
        assert len(body["keep"]) == 3 and len(body["retire"]) == 3

    def test_delete_without_confirmation_is_refused_before_submitting(self, client):
        """It must fail as a 400, not as a job that fails asynchronously."""
        self._seed()
        res = client.post("/api/retention", json={
            "keep": 3, "mode": "delete", "apply": True, "confirm_delete": False,
        })
        assert res.status_code == 400
        assert "permanent" in res.json()["detail"].lower()
        assert jobs.runner.snapshot()["current"] is None, "no job may have been started"

    def test_unknown_mode_rejected(self, client):
        res = client.post("/api/retention", json={"mode": "nuke"})
        assert res.status_code == 400

    def test_nothing_to_retire_is_not_a_job(self, client):
        self._seed()
        body = client.post("/api/retention",
                           json={"keep": 50, "mode": "archive", "apply": True}).json()
        assert body["applied"] is False
        assert jobs.runner.snapshot()["current"] is None

    def test_archive_is_the_default_mode(self, client):
        self._seed()
        assert client.post("/api/retention", json={"keep": 3}).json()["mode"] == "archive"


class TestQueueEndpoints:
    def _add(self):
        from reelbot.publish import queue

        return queue.add(queue.QueueItem(
            id="q1", format="quiz", title="T", caption="c", video_path="v.mp4",
        ))

    def test_approve_and_reject(self, client):
        self._add()
        assert client.post("/api/queue/q1/approve").json()["status"] == "approved"
        assert client.post("/api/queue/q1/reject").json()["status"] == "rejected"

    def test_unknown_item_is_404(self, client):
        assert client.post("/api/queue/nope/approve").status_code == 404

    def test_unknown_action_is_rejected(self, client):
        self._add()
        assert client.post("/api/queue/q1/explode").status_code in (400, 404)

    def test_publish_with_nothing_approved(self, client):
        assert client.post("/api/publish").status_code == 400


class TestMediaServing:
    @pytest.mark.parametrize("name", ["../.env", "..%2f.env", "../../etc/passwd"])
    def test_path_traversal_blocked(self, client, name):
        assert client.get(f"/media/{name}").status_code in (307, 404)

    def test_missing_file_is_404(self, client):
        assert client.get("/media/definitely-not-here.mp4").status_code == 404


class TestJobRunner:
    def test_one_job_at_a_time(self):
        import threading

        runner = jobs.JobRunner()
        release = threading.Event()
        runner.submit("slow", lambda: release.wait(2) or {})
        with pytest.raises(RuntimeError, match="already running"):
            runner.submit("other", lambda: {})
        release.set()

    def test_failure_is_recorded_not_raised(self):
        runner = jobs.JobRunner()
        job = runner.submit("bad", lambda: (_ for _ in ()).throw(ValueError("boom")))
        for _ in range(50):
            if job.status in (jobs.DONE, jobs.FAILED):
                break
            __import__("time").sleep(0.05)
        assert job.status == jobs.FAILED and "boom" in job.message

    def test_snapshot_shape(self):
        snap = jobs.JobRunner().snapshot()
        assert snap["current"] is None and snap["recent"] == []
