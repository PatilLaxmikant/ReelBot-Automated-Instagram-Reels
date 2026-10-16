"""Story reshare: backdrop content, layout, and failure isolation.

The defect these guard against shipped: the backdrop drew only a "NEW TODAY"
badge and a tap prompt, so every story was byte-identical no matter which reel
it promoted. Seven stories went out that way and none of them said what the
reel was about.
"""
from __future__ import annotations

import pytest
from PIL import Image

from reelbot.content import fallbacks
from reelbot.formats import ALL_FORMATS
from reelbot.render.story import (
    STICKER,
    STORY_SAFE_BOTTOM,
    STORY_SAFE_TOP,
    create_story_background,
    story_path,
    style_for,
)
from reelbot.render.theme import HEIGHT, WIDTH

#: JPEG ringing around a hard edge bleeds a few levels into neighbouring rows,
#: so an exact comparison flags compression noise as content.
NOISE = 14


def _rows_have_content(image: Image.Image, top: int, bottom: int) -> bool:
    """True if any row in the band departs meaningfully from its left edge.

    The backdrop is a full-frame gradient, so 'empty' means 'matches the
    gradient at this row', not 'is one flat colour'.
    """
    pixels = image.load()
    for y in range(max(0, top), min(bottom, HEIGHT), 3):
        edge = pixels[4, y]
        for x in range(8, WIDTH - 8, 3):
            pixel = pixels[x, y]
            if max(abs(pixel[c] - edge[c]) for c in range(3)) > NOISE:
                return True
    return False


def render(lesson: dict, tmp_path, name="bg.jpg") -> Image.Image:
    return Image.open(create_story_background(lesson, tmp_path / name)).convert("RGB")


@pytest.fixture(scope="module")
def backdrop(tmp_path_factory):
    path = tmp_path_factory.mktemp("story") / "bg.jpg"
    lesson = fallbacks.pick("quiz")
    create_story_background({"title": lesson["title"], "format": "quiz"}, path)
    return Image.open(path).convert("RGB")


class TestRelatesToTheReel:
    """The regression: a backdrop that says nothing about what it promotes."""

    def test_formats_produce_different_backdrops(self, tmp_path):
        """Every story used to be the same bytes regardless of the reel."""
        digests = set()
        for fmt in ALL_FORMATS:
            lesson = fallbacks.pick(fmt)
            path = create_story_background(
                {"title": lesson["title"], "format": fmt}, tmp_path / f"{fmt}.jpg"
            )
            digests.add(path.read_bytes())
        assert len(digests) == len(ALL_FORMATS), (
            "backdrops are not distinct per format - the story says nothing "
            "about which reel it promotes"
        )

    def test_different_titles_produce_different_backdrops(self, tmp_path):
        a = create_story_background(
            {"title": "Stop Saying Very Busy", "format": "vocab"}, tmp_path / "a.jpg")
        b = create_story_background(
            {"title": "Three Phrases That Sound Native", "format": "vocab"}, tmp_path / "b.jpg")
        assert a.read_bytes() != b.read_bytes()

    def test_headline_band_carries_content(self, backdrop):
        """The reel's own hook is drawn above the sticker."""
        assert _rows_have_content(backdrop, STORY_SAFE_TOP, STICKER.top_px - 8)

    @pytest.mark.parametrize("fmt", ALL_FORMATS)
    def test_every_format_has_its_own_accent_and_prompt(self, fmt):
        accent, prompt = style_for(fmt)
        assert accent and prompt
        others = {style_for(f) for f in ALL_FORMATS if f != fmt}
        assert (accent, prompt) not in others, f"{fmt} shares its style with another format"

    def test_unknown_format_falls_back_to_a_usable_style(self):
        accent, prompt = style_for("")
        assert accent and prompt

    def test_long_title_still_fits_the_headline_band(self, tmp_path):
        image = render({"title": "A " * 40, "format": "quiz"}, tmp_path, "long.jpg")
        assert not _rows_have_content(image, STICKER.top_px + 8, STICKER.bottom_px - 8)


class TestBackdropLayout:
    def test_sticker_band_is_left_clear(self, backdrop):
        """Instagram draws the reshared reel here; anything of ours collides."""
        assert not _rows_have_content(backdrop, STICKER.top_px + 8, STICKER.bottom_px - 8)

    def test_nothing_above_the_story_safe_top(self, backdrop):
        assert not _rows_have_content(backdrop, 0, STORY_SAFE_TOP - 4)

    def test_nothing_below_the_story_safe_bottom(self, backdrop):
        assert not _rows_have_content(backdrop, STORY_SAFE_BOTTOM + 4, HEIGHT)

    def test_tap_prompt_sits_below_the_sticker(self, backdrop):
        assert _rows_have_content(backdrop, STICKER.bottom_px + 8, STORY_SAFE_BOTTOM)

    def test_canvas_is_full_story_size(self, backdrop):
        assert backdrop.size == (WIDTH, HEIGHT)

    def test_sticker_leaves_room_for_a_headline(self):
        """The placement exists to buy space above the preview."""
        assert STICKER.top_px - STORY_SAFE_TOP >= 300

    def test_sticker_stays_inside_the_story_safe_area(self):
        assert STICKER.top_px >= STORY_SAFE_TOP
        assert STICKER.bottom_px <= STORY_SAFE_BOTTOM

    def test_story_path_is_distinct_from_the_reel(self):
        assert story_path("quiz_1").name.startswith("story_")


class TestShareFailureIsolation:
    def test_missing_backdrop_returns_none(self, tmp_path):
        from reelbot.publish.instagram import share_to_story

        assert share_to_story("123", tmp_path / "nope.jpg") is None

    def test_upload_failure_returns_none(self, backdrop, tmp_path):
        from reelbot.publish import instagram

        path = tmp_path / "bg.jpg"
        backdrop.save(path)

        class Boom:
            def photo_upload_to_story(self, *a, **k):
                raise RuntimeError("rate limited")

        assert instagram.share_to_story("123", path, client=Boom()) is None

    def test_sticker_placement_is_sent_to_instagram(self, backdrop, tmp_path):
        """The backdrop is laid out around STICKER, so the sticker must match."""
        from reelbot.publish import instagram

        path = tmp_path / "bg.jpg"
        backdrop.save(path)

        class Story:
            pk = "999"

        class Ok:
            def __init__(self): self.medias = None

            def photo_upload_to_story(self, background, medias=None, **k):
                self.medias = medias
                return Story()

        client = Ok()
        assert instagram.share_to_story("123", path, client=client) == "999"
        sticker = client.medias[0]
        assert sticker.media_pk == 123
        assert sticker.y == pytest.approx(STICKER.y)
        assert sticker.height == pytest.approx(STICKER.height)


class TestRunnerWiring:
    def _settings(self, share: bool):
        return type("S", (), {"share_to_story": share, "auto_publish": False})()

    def test_story_is_skipped_when_disabled(self, monkeypatch):
        from reelbot.planner import runner
        from reelbot.publish.queue import QueueItem

        monkeypatch.setattr(runner, "get_settings", lambda: self._settings(False))
        item = QueueItem(id="x", format="quiz", title="T", caption="c", video_path="v.mp4")
        assert runner._reshare_to_story(item, "123") is None

    def test_format_is_passed_through_to_the_backdrop(self, monkeypatch):
        """Without the format the backdrop cannot pick a badge or accent."""
        from reelbot.planner import runner
        from reelbot.publish.queue import QueueItem

        seen = {}

        def fake_background(lesson, path):
            seen.update(lesson)
            return path

        monkeypatch.setattr(runner, "get_settings", lambda: self._settings(True))
        monkeypatch.setattr("reelbot.render.story.create_story_background", fake_background)
        monkeypatch.setattr("reelbot.publish.instagram.share_to_story", lambda *a, **k: "s1")

        item = QueueItem(id="x", format="mistake", title="Confusing Words",
                         caption="c", video_path="v.mp4")
        assert runner._reshare_to_story(item, "123") == "s1"
        assert seen.get("format") == "mistake"
        assert seen.get("title") == "Confusing Words"

    def test_story_failure_does_not_raise(self, monkeypatch):
        from reelbot.planner import runner
        from reelbot.publish.queue import QueueItem

        monkeypatch.setattr(runner, "get_settings", lambda: self._settings(True))
        monkeypatch.setattr(
            "reelbot.render.story.create_story_background",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("disk full")),
        )
        item = QueueItem(id="x", format="quiz", title="T", caption="c", video_path="v.mp4")
        assert runner._reshare_to_story(item, "123") is None

    def test_no_media_id_means_no_story(self, monkeypatch):
        from reelbot.planner import runner
        from reelbot.publish.queue import QueueItem

        monkeypatch.setattr(runner, "get_settings", lambda: self._settings(True))
        item = QueueItem(id="x", format="quiz", title="T", caption="c", video_path="v.mp4")
        assert runner._reshare_to_story(item, "") is None


class TestSetting:
    @pytest.mark.parametrize(
        "raw, expected",
        [("true", True), ("false", False), ("1", True), ("0", False),
         ("yes", True), ("no", False), ("", True), (None, True), ("garbage", True)],
    )
    def test_share_to_story_parsing(self, raw, expected):
        from reelbot.settings import _bool

        assert _bool(raw, True) is expected
