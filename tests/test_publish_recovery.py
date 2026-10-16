"""Uploads that raise after the reel is already live.

This shipped: instagrapi ends ``clip_upload`` with a call to
``/api/v1/qe/expose/``, an A/B-testing endpoint Instagram has removed. It 404s
*after* the media is configured, so the reel went live, the caller saw an
exception, and the queue recorded a failure for a post that exists. A retry
would have published the same reel twice.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from reelbot.publish import instagram


class FakeMedia:
    def __init__(self, pk: str, caption: str, minutes_ago: float = 1.0):
        self.pk = pk
        self.caption_text = caption
        self.taken_at = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)


class FakeClient:
    """A client whose upload raises the way instagrapi's expose() does."""

    user_id = "42"

    def __init__(self, medias=(), raise_on_upload=True):
        self._medias = list(medias)
        self._raise = raise_on_upload
        self.expose_calls = 0

    def expose(self):
        self.expose_calls += 1
        raise RuntimeError("404 Client Error: Not Found for url: .../v1/qe/expose/")

    def clip_upload(self, path, caption, **kwargs):
        if self._raise:
            self.expose()
        return FakeMedia("999", caption)

    def user_medias(self, user_id, amount=3):
        return self._medias[:amount]


@pytest.fixture
def video(tmp_path):
    path = tmp_path / "reel.mp4"
    path.write_bytes(b"not really a video")
    return path


class TestExposeIsNeutralised:
    def test_expose_becomes_a_no_op(self):
        client = FakeClient()
        instagram._silence_expose(client)
        assert client.expose() == {}

    def test_a_neutralised_upload_returns_the_media(self, video, monkeypatch):
        client = FakeClient()
        instagram._silence_expose(client)
        monkeypatch.setattr(instagram, "_client", lambda: client)

        assert instagram.upload_reel(video, "a caption") == "999"
        assert client.expose_calls == 0, "expose() should never have run"

    def test_a_client_that_rejects_patching_does_not_explode(self):
        class Sealed:
            __slots__ = ()

        instagram._silence_expose(Sealed())  # must not raise


class TestReconciliation:
    """The safety net, for any upload that raises after the post is live."""

    def test_a_live_post_is_reported_as_published(self, video, monkeypatch):
        caption = "Ending a chat is where textbook English sounds most robotic"
        client = FakeClient(medias=[FakeMedia("3982912541024182825", caption)])
        monkeypatch.setattr(instagram, "_client", lambda: client)

        assert instagram.upload_reel(video, caption) == "3982912541024182825"

    def test_a_genuine_failure_still_raises(self, video, monkeypatch):
        client = FakeClient(medias=[FakeMedia("111", "some other reel entirely")])
        monkeypatch.setattr(instagram, "_client", lambda: client)

        with pytest.raises(instagram.PublishError):
            instagram.upload_reel(video, "the caption we tried to post")

    def test_an_older_post_with_the_same_caption_is_not_claimed(self, video, monkeypatch):
        """Re-posting a topic must not resolve to last week's upload."""
        caption = "a caption used before"
        client = FakeClient(medias=[FakeMedia("old", caption, minutes_ago=60 * 24)])
        monkeypatch.setattr(instagram, "_client", lambda: client)

        with pytest.raises(instagram.PublishError):
            instagram.upload_reel(video, caption)

    def test_an_unreadable_account_is_not_a_success(self, video, monkeypatch):
        """A failed lookup must not be reported as a published reel."""

        class Blind(FakeClient):
            def user_medias(self, user_id, amount=3):
                raise RuntimeError("rate limited")

        monkeypatch.setattr(instagram, "_client", lambda: Blind())
        with pytest.raises(instagram.PublishError):
            instagram.upload_reel(video, "a caption")

    def test_a_naive_timestamp_is_handled(self, video, monkeypatch):
        """instagrapi has returned both aware and naive datetimes."""
        caption = "a caption"
        media = FakeMedia("naive", caption)
        media.taken_at = datetime.now(timezone.utc).replace(tzinfo=None)
        monkeypatch.setattr(instagram, "_client", lambda: FakeClient(medias=[media]))

        assert instagram.upload_reel(video, caption) == "naive"

    def test_a_missing_video_never_reaches_instagram(self, tmp_path):
        with pytest.raises(instagram.PublishError, match="Video not found"):
            instagram.upload_reel(tmp_path / "nope.mp4", "caption")


class TestCaptionKey:
    def test_whitespace_and_case_do_not_matter(self):
        assert instagram._caption_key("Hello   World") == instagram._caption_key("hello world")

    def test_a_blank_caption_matches_nothing(self):
        client = FakeClient(medias=[FakeMedia("x", "")])
        assert instagram._find_just_published(client, "") == ""

    def test_captions_differing_after_the_key_still_match(self):
        """Hashtags are appended per post; the head identifies the reel."""
        head = "x" * instagram._CAPTION_KEY_CHARS
        assert instagram._caption_key(head + " #one") == instagram._caption_key(head + " #two")
