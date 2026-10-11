"""Unit tests for services/publisher.py — fan-out, isolation, cleanup."""
import asyncio
import os
import tempfile

import pytest

from services.publisher import DestResult, render_results

from fakes import FakeBot, FakeInstagram, FakeLinkedIn, make_user

PHOTOS = ["ph1", "ph2"]


@pytest.fixture
def tracked_temp_files(monkeypatch):
    real_mkstemp = tempfile.mkstemp
    created = []

    def tracking_mkstemp(*args, **kwargs):
        fd, path = real_mkstemp(*args, **kwargs)
        created.append(path)
        return fd, path

    monkeypatch.setattr(tempfile, "mkstemp", tracking_mkstemp)
    return created


class TestHappyPath:
    async def test_both_destinations_publish(self, make_publisher):
        li, ig = FakeLinkedIn(), FakeInstagram()
        results = await make_publisher(linkedin=li, instagram=ig).publish_to_all(
            make_user(), "post text", PHOTOS
        )
        assert [(r.name, r.ok, r.skipped) for r in results] == [
            ("LinkedIn", True, False),
            ("Instagram", True, False),
        ]
        assert li.posts == [
            (
                "li-token",
                "urn:li:person:abc",
                "post text",
                ["urn:li:digitalAssetAsset:1", "urn:li:digitalAssetAsset:2"],
            )
        ]
        assert li.uploaded_images == [b"jpeg-bytes", b"jpeg-bytes"]
        assert ig.calls[0]["text"] == "post text"
        assert len(ig.calls[0]["photo_paths"]) == 2
        assert ig.calls[0]["paths_existed"] == [True, True]

    async def test_temp_files_removed_after_publish(self, make_publisher, tracked_temp_files):
        await make_publisher().publish_to_all(make_user(), "text", PHOTOS)
        assert len(tracked_temp_files) == 2
        assert all(not os.path.exists(path) for path in tracked_temp_files)

    async def test_temp_files_removed_on_cancellation(self, make_publisher, tracked_temp_files):
        # The `finally` cleanup only proves itself on BaseException: simulate a
        # cancelled publish by making create_post raise CancelledError.
        li = FakeLinkedIn(create_post_exc=asyncio.CancelledError())
        with pytest.raises(asyncio.CancelledError):
            await make_publisher(linkedin=li).publish_to_all(make_user(), "text", PHOTOS)
        assert len(tracked_temp_files) == 2
        assert all(not os.path.exists(path) for path in tracked_temp_files)


class TestSkips:
    @pytest.mark.parametrize(
        "overrides",
        [
            {"linkedin_access_token": None, "linkedin_person_urn": None},
            {"linkedin_access_token": "tok", "linkedin_person_urn": None},
            {"linkedin_access_token": None, "linkedin_person_urn": "urn"},
        ],
    )
    async def test_linkedin_not_connected(self, make_publisher, overrides):
        results = await make_publisher().publish_to_all(make_user(**overrides), "text", [])
        assert results[0].skipped is True
        assert results[0].detail == "не подключён"

    @pytest.mark.parametrize(
        "overrides",
        [
            {"instagram_username": None, "instagram_password_encrypted": None},
            {"instagram_username": "ig", "instagram_password_encrypted": None},
        ],
    )
    async def test_instagram_not_connected(self, make_publisher, overrides):
        overrides.setdefault("instagram_sessionid_encrypted", None)
        results = await make_publisher().publish_to_all(
            make_user(**overrides), "text", PHOTOS
        )
        assert results[1].skipped is True
        assert results[1].detail == "не подключён"

    async def test_instagram_sessionid_only_is_connected(self, make_publisher):
        ig = FakeInstagram()
        user = make_user(instagram_password_encrypted=None, instagram_sessionid_encrypted="enc-session")
        results = await make_publisher(instagram=ig).publish_to_all(user, "text", PHOTOS)
        assert results[1].ok is True
        assert ig.calls[0]["sessionid"] == "enc-session"
        assert ig.calls[0]["password"] is None

    async def test_instagram_without_photos_skipped(self, make_publisher):
        ig = FakeInstagram()
        results = await make_publisher(instagram=ig).publish_to_all(make_user(), "text", [])
        assert results[1].skipped is True
        assert results[1].detail == "нет фото (требуется медиа)"
        assert ig.calls == []

    async def test_not_connected_checked_before_pause(self, make_publisher):
        user = make_user(
            instagram_username=None,
            instagram_password_encrypted=None,
            instagram_sessionid_encrypted=None,
        )
        results = await make_publisher().publish_to_all(user, "text", [], ig_enabled=False)
        assert results[1].detail == "не подключён"

    async def test_pause_checked_before_no_photos(self, make_publisher):
        results = await make_publisher().publish_to_all(make_user(), "text", [], ig_enabled=False)
        assert results[1].detail == "пауза"


class TestPause:
    async def test_per_post_override_pauses_both(self, make_publisher):
        li, ig = FakeLinkedIn(), FakeInstagram()
        results = await make_publisher(linkedin=li, instagram=ig).publish_to_all(
            make_user(), "text", PHOTOS, li_enabled=False, ig_enabled=False
        )
        assert results[0].skipped is True and results[0].detail == "пауза"
        assert results[1].skipped is True and results[1].detail == "пауза"
        assert li.posts == []
        assert ig.calls == []

    async def test_global_toggles_pause_both(self, make_publisher):
        li, ig = FakeLinkedIn(), FakeInstagram()
        user = make_user(linkedin_enabled=False, instagram_enabled=False)
        results = await make_publisher(linkedin=li, instagram=ig).publish_to_all(user, "text", PHOTOS)
        assert results[0].detail == "пауза"
        assert results[1].detail == "пауза"
        assert li.posts == []
        assert ig.calls == []

    @pytest.mark.parametrize(
        "override,global_enabled,expected_detail",
        [
            (False, True, "пауза"),
            (True, False, "опубликован"),
            (None, False, "пауза"),
            (None, True, "опубликован"),
        ],
    )
    async def test_override_beats_global_toggle(
        self, make_publisher, override, global_enabled, expected_detail
    ):
        li = FakeLinkedIn()
        user = make_user(linkedin_enabled=global_enabled)
        results = await make_publisher(linkedin=li).publish_to_all(
            user, "text", PHOTOS, li_enabled=override
        )
        assert results[0].detail == expected_detail
        assert (li.posts != []) is (expected_detail == "опубликован")


class TestPartialFailures:
    async def test_one_upload_fails_post_keeps_surviving_urns(self, make_publisher):
        li = FakeLinkedIn(upload_fail_indexes={0})
        results = await make_publisher(linkedin=li).publish_to_all(make_user(), "text", PHOTOS)
        assert results[0].ok is True
        assert li.posts[0][3] == ["urn:li:digitalAssetAsset:1"]

    async def test_all_uploads_fail_post_created_text_only(self, make_publisher):
        li = FakeLinkedIn(upload_fail_indexes={0, 1})
        results = await make_publisher(linkedin=li).publish_to_all(make_user(), "text", PHOTOS)
        assert results[0].ok is True
        assert li.posts[0][3] is None

    async def test_linkedin_create_post_fails_instagram_unaffected(self, make_publisher):
        li = FakeLinkedIn(create_post_exc=RuntimeError("li down"))
        ig = FakeInstagram()
        results = await make_publisher(linkedin=li, instagram=ig).publish_to_all(
            make_user(), "text", PHOTOS
        )
        assert results[0].ok is False
        assert results[0].skipped is False
        assert results[0].detail == "li down"
        assert results[1].ok is True
        assert len(ig.calls) == 1

    async def test_instagram_publish_fails_linkedin_unaffected(self, make_publisher):
        li = FakeLinkedIn()
        ig = FakeInstagram(exc=RuntimeError("ig down"))
        results = await make_publisher(linkedin=li, instagram=ig).publish_to_all(
            make_user(), "text", PHOTOS
        )
        assert results[0].ok is True
        assert results[1].ok is False
        assert results[1].detail == "ig down"

    async def test_all_downloads_fail_linkedin_text_only_instagram_skipped(self, make_publisher):
        bot = FakeBot(fail_download_for=set(PHOTOS))
        li, ig = FakeLinkedIn(), FakeInstagram()
        results = await make_publisher(bot=bot, linkedin=li, instagram=ig).publish_to_all(
            make_user(), "text", PHOTOS
        )
        assert results[0].ok is True
        assert li.posts[0][3] is None
        assert results[1].skipped is True
        assert "нет фото" in results[1].detail

    async def test_partial_download_failure_publishes_surviving_photo(self, make_publisher):
        bot = FakeBot(fail_download_for={"ph1"})
        li = FakeLinkedIn()
        results = await make_publisher(bot=bot, linkedin=li).publish_to_all(
            make_user(), "text", PHOTOS
        )
        assert len(li.uploaded_images) == 1
        assert results[0].ok is True


class TestRenderResults:
    @pytest.mark.parametrize(
        "result,icon",
        [
            (DestResult("X", True, "d"), "✅"),
            (DestResult("X", False, "d"), "❌"),
            (DestResult("X", False, "d", skipped=True), "⏸"),
        ],
    )
    def test_dest_result_icon(self, result, icon):
        assert result.icon == icon

    def test_render_results_lines(self):
        results = [
            DestResult("LinkedIn", True, "опубликован"),
            DestResult("Instagram", False, "не подключён", skipped=True),
        ]
        assert render_results(results) == "✅ LinkedIn: опубликован\n⏸ Instagram: не подключён"
