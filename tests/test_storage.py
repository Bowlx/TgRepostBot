"""Unit tests for services/storage.py — SQLite persistence and migrations."""
import aiosqlite
import pytest

from services.storage import Storage

# Pre-migration schemas: what an older release of the bot would have on disk.
OLD_USERS_SCHEMA = """
CREATE TABLE users (
    user_id INTEGER PRIMARY KEY,
    source_lang TEXT NOT NULL DEFAULT 'ru',
    target_lang TEXT NOT NULL DEFAULT 'en',
    linkedin_access_token TEXT,
    linkedin_person_urn TEXT
)
"""

OLD_PENDING_POSTS_SCHEMA = """
CREATE TABLE pending_posts (
    user_id INTEGER PRIMARY KEY,
    original_text TEXT NOT NULL,
    translated_text TEXT NOT NULL,
    photo_file_ids TEXT NOT NULL DEFAULT '[]'
)
"""

OLD_PENDING_APPROVALS_SCHEMA = """
CREATE TABLE pending_approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    original_text TEXT NOT NULL,
    translated_text TEXT NOT NULL,
    photo_file_ids TEXT NOT NULL DEFAULT '[]'
)
"""


async def _raw_execute(db_path: str, sql: str, params=()):
    async with aiosqlite.connect(db_path) as db:
        await db.execute(sql, params)
        await db.commit()


class TestInit:
    async def test_creates_all_tables(self, tmp_path):
        storage = Storage(str(tmp_path / "db.sqlite"))
        await storage.init()
        async with aiosqlite.connect(storage.db_path) as db:
            cursor = await db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            names = {row[0] for row in await cursor.fetchall()}
        assert {"settings", "users", "pending_posts", "pending_approvals"} <= names

    async def test_reinit_idempotent(self, tmp_path):
        storage = Storage(str(tmp_path / "db.sqlite"))
        await storage.init()
        await storage.init()
        assert await storage.get_setting("missing") is None  # db still usable


class TestMigrations:
    async def test_users_old_schema_gains_columns_and_keeps_data(self, tmp_path):
        db_path = str(tmp_path / "db.sqlite")
        await _raw_execute(db_path, OLD_USERS_SCHEMA)
        await _raw_execute(
            db_path,
            "INSERT INTO users (user_id, source_lang, target_lang, linkedin_access_token, linkedin_person_urn)"
            " VALUES (7, 'de', 'fr', 'tok', 'urn')",
        )
        storage = Storage(db_path)
        await storage.init()
        user = await storage.get_user(7)
        assert user is not None
        assert (user.source_lang, user.target_lang) == ("de", "fr")
        assert user.linkedin_access_token == "tok"
        assert user.linkedin_person_urn == "urn"
        assert user.translate_enabled is True
        assert user.approve_enabled is False
        assert user.linkedin_enabled is True
        assert user.instagram_username is None
        assert user.instagram_enabled is True

    async def test_pending_posts_old_schema_gets_defaults(self, tmp_path):
        db_path = str(tmp_path / "db.sqlite")
        await _raw_execute(db_path, OLD_PENDING_POSTS_SCHEMA)
        await _raw_execute(
            db_path,
            "INSERT INTO pending_posts (user_id, original_text, translated_text, photo_file_ids)"
            " VALUES (7, 'orig', 'trans', '[\"f1\"]')",
        )
        storage = Storage(db_path)
        await storage.init()
        pending = await storage.get_pending_post(7)
        assert pending is not None
        assert pending.original_text == "orig"
        assert pending.translated_text == "trans"
        assert pending.photo_file_ids == ["f1"]
        # ALTER TABLE fills migrated rows with column defaults, not with the
        # save-time active_text derivation.
        assert pending.active_text == ""
        assert pending.active_mode == "translated"
        assert pending.li_enabled is True
        assert pending.ig_enabled is True

    async def test_pending_approvals_old_schema_gets_defaults(self, tmp_path):
        db_path = str(tmp_path / "db.sqlite")
        await _raw_execute(db_path, OLD_PENDING_APPROVALS_SCHEMA)
        await _raw_execute(
            db_path,
            "INSERT INTO pending_approvals (id, user_id, original_text, translated_text, photo_file_ids)"
            " VALUES (3, 7, 'orig', 'trans', '[]')",
        )
        storage = Storage(db_path)
        await storage.init()
        approval = await storage.get_approval(3)
        assert approval is not None
        assert approval.active_text == ""
        assert approval.active_mode == "translated"
        assert approval.li_enabled is True
        assert approval.ig_enabled is True


class TestSettings:
    async def test_roundtrip_missing_and_overwrite(self, storage):
        assert await storage.get_setting("missing") is None
        await storage.set_setting("k", "v1")
        assert await storage.get_setting("k") == "v1"
        await storage.set_setting("k", "v2")
        assert await storage.get_setting("k") == "v2"

    async def test_get_all_settings(self, storage):
        await storage.set_setting("a", "1")
        await storage.set_setting("b", "2")
        assert await storage.get_all_settings() == {"a": "1", "b": "2"}


class TestUsers:
    async def test_create_user_defaults(self, storage):
        await storage.create_user(1)
        user = await storage.get_user(1)
        assert user.user_id == 1
        assert user.source_lang == "ru"
        assert user.target_lang == "en"
        assert user.translate_enabled is True
        assert user.approve_enabled is False
        assert user.linkedin_enabled is True
        assert user.instagram_enabled is True
        assert user.linkedin_access_token is None
        assert user.instagram_username is None

    async def test_create_user_custom_langs(self, storage):
        await storage.create_user(1, "de", "fr")
        user = await storage.get_user(1)
        assert (user.source_lang, user.target_lang) == ("de", "fr")

    async def test_get_missing_user(self, storage):
        assert await storage.get_user(999) is None

    async def test_create_existing_user_not_overwritten(self, storage):
        await storage.create_user(1)
        await storage.update_languages(1, "fr", "de")
        await storage.create_user(1, "es", "it")
        user = await storage.get_user(1)
        assert (user.source_lang, user.target_lang) == ("fr", "de")

    async def test_update_languages(self, storage):
        await storage.create_user(1)
        await storage.update_languages(1, "fr", "de")
        user = await storage.get_user(1)
        assert (user.source_lang, user.target_lang) == ("fr", "de")

    @pytest.mark.parametrize(
        "setter,attr,default",
        [
            ("set_translate_enabled", "translate_enabled", True),
            ("set_approve_enabled", "approve_enabled", False),
            ("set_linkedin_enabled", "linkedin_enabled", True),
            ("set_instagram_enabled", "instagram_enabled", True),
        ],
    )
    async def test_set_enabled_toggles(self, storage, setter, attr, default):
        await storage.create_user(1)
        assert getattr(await storage.get_user(1), attr) is default
        await getattr(storage, setter)(1, not default)
        assert getattr(await storage.get_user(1), attr) is (not default)
        await getattr(storage, setter)(1, default)
        assert getattr(await storage.get_user(1), attr) is default


class TestInstagramCreds:
    async def test_set_instagram_creds(self, storage):
        await storage.create_user(1)
        await storage.set_instagram_sessionid(1, "user", "enc-session")
        await storage.set_instagram_creds(1, "user", "enc-pass", "enc-totp")
        user = await storage.get_user(1)
        assert user.instagram_username == "user"
        assert user.instagram_password_encrypted == "enc-pass"
        assert user.instagram_totp_secret_encrypted == "enc-totp"
        assert user.instagram_sessionid_encrypted is None
        assert user.instagram_enabled is True

    async def test_set_instagram_creds_reenables(self, storage):
        await storage.create_user(1)
        await storage.set_instagram_enabled(1, False)
        await storage.set_instagram_creds(1, "user", "enc-pass")
        assert (await storage.get_user(1)).instagram_enabled is True

    async def test_set_instagram_sessionid(self, storage):
        await storage.create_user(1)
        await storage.set_instagram_creds(1, "user", "enc-pass", "enc-totp")
        await storage.set_instagram_sessionid(1, "user2", "enc-session")
        user = await storage.get_user(1)
        assert user.instagram_username == "user2"
        assert user.instagram_sessionid_encrypted == "enc-session"
        assert user.instagram_password_encrypted is None
        assert user.instagram_totp_secret_encrypted is None
        assert user.instagram_enabled is True

    async def test_clear_instagram_creds(self, storage):
        await storage.create_user(1)
        await storage.set_instagram_creds(1, "user", "enc-pass", "enc-totp")
        await storage.clear_instagram_creds(1)
        user = await storage.get_user(1)
        assert user.instagram_username is None
        assert user.instagram_password_encrypted is None
        assert user.instagram_totp_secret_encrypted is None
        assert user.instagram_sessionid_encrypted is None

    async def test_clear_instagram_creds_keeps_enabled(self, storage):
        # Characterization: clearing creds does not reset the enabled toggle.
        await storage.create_user(1)
        await storage.set_instagram_creds(1, "user", "enc-pass")
        await storage.clear_instagram_creds(1)
        assert (await storage.get_user(1)).instagram_enabled is True


class TestLinkedIn:
    async def test_update_linkedin_token(self, storage):
        await storage.create_user(1)
        await storage.update_linkedin_token(1, "tok", "urn")
        user = await storage.get_user(1)
        assert user.linkedin_access_token == "tok"
        assert user.linkedin_person_urn == "urn"


class TestGetAllActiveUsers:
    async def test_filter_by_connected_destinations(self, storage):
        await storage.create_user(1)  # nothing connected
        await storage.create_user(2)
        await storage.update_linkedin_token(2, "tok", "urn")
        await storage.create_user(3)
        await storage.set_instagram_creds(3, "ig", "enc-pass")
        await storage.create_user(4)
        await storage.set_instagram_sessionid(4, "ig", "enc-session")
        active = await storage.get_all_active_users()
        assert {u.user_id for u in active} == {2, 3, 4}

    async def test_disabled_but_connected_still_listed(self, storage):
        # Characterization: the filter is by connection, not by enabled flag.
        await storage.create_user(1)
        await storage.update_linkedin_token(1, "tok", "urn")
        await storage.set_linkedin_enabled(1, False)
        active = await storage.get_all_active_users()
        assert [u.user_id for u in active] == [1]

    async def test_username_without_secret_still_listed(self, storage):
        # Characterization: storage counts instagram_username alone as connected,
        # while Publisher requires password or sessionid — such a user is listed
        # here but would be skipped as "не подключён" at publish time.
        await storage.create_user(1)
        await _raw_execute(
            storage.db_path,
            "UPDATE users SET instagram_username = 'ghost' WHERE user_id = 1",
        )
        active = await storage.get_all_active_users()
        assert [u.user_id for u in active] == [1]


class TestPendingPosts:
    async def test_roundtrip(self, storage):
        await storage.save_pending_post(1, "orig", "trans", ["f1", "f2"], li_enabled=False)
        pending = await storage.get_pending_post(1)
        assert pending.user_id == 1
        assert pending.original_text == "orig"
        assert pending.translated_text == "trans"
        assert pending.photo_file_ids == ["f1", "f2"]
        assert pending.li_enabled is False
        assert pending.ig_enabled is True

    @pytest.mark.parametrize(
        "original,translated,mode,active",
        [
            ("orig", "trans", "translated", "trans"),
            ("orig", "", "original", "orig"),
            ("same", "same", "original", "same"),
        ],
    )
    async def test_active_mode_logic(self, storage, original, translated, mode, active):
        await storage.save_pending_post(1, original, translated, [])
        pending = await storage.get_pending_post(1)
        assert pending.active_mode == mode
        assert pending.active_text == active

    async def test_resave_replaces(self, storage):
        await storage.save_pending_post(1, "a", "a-tr", ["f1"])
        await storage.save_pending_post(1, "b", "b-tr", [])
        pending = await storage.get_pending_post(1)
        assert pending.original_text == "b"
        assert pending.translated_text == "b-tr"
        assert pending.photo_file_ids == []

    async def test_get_missing(self, storage):
        assert await storage.get_pending_post(1) is None

    async def test_delete(self, storage):
        await storage.save_pending_post(1, "a", "a-tr", [])
        await storage.delete_pending_post(1)
        assert await storage.get_pending_post(1) is None

    async def test_set_pending_active(self, storage):
        await storage.save_pending_post(1, "orig", "trans", [])
        await storage.set_pending_active(1, "original", "orig")
        pending = await storage.get_pending_post(1)
        assert pending.active_mode == "original"
        assert pending.active_text == "orig"

    @pytest.mark.parametrize("dest,attr", [("li", "li_enabled"), ("ig", "ig_enabled")])
    async def test_set_pending_dest(self, storage, dest, attr):
        await storage.save_pending_post(1, "orig", "trans", [])
        await storage.set_pending_dest(1, dest, False)
        assert getattr(await storage.get_pending_post(1), attr) is False
        await storage.set_pending_dest(1, dest, True)
        assert getattr(await storage.get_pending_post(1), attr) is True


class TestApprovals:
    async def test_roundtrip(self, storage):
        approval_id = await storage.create_approval(1, "orig", "trans", ["f1"], ig_enabled=False)
        approval = await storage.get_approval(approval_id)
        assert approval.id == approval_id
        assert approval.user_id == 1
        assert approval.original_text == "orig"
        assert approval.translated_text == "trans"
        assert approval.photo_file_ids == ["f1"]
        assert approval.active_mode == "translated"
        assert approval.active_text == "trans"
        assert approval.li_enabled is True
        assert approval.ig_enabled is False

    async def test_records_coexist_with_monotonic_ids(self, storage):
        first = await storage.create_approval(1, "a", "a-tr", [])
        second = await storage.create_approval(1, "b", "b-tr", [])
        assert second > first
        assert (await storage.get_approval(first)).original_text == "a"
        assert (await storage.get_approval(second)).original_text == "b"

    async def test_get_missing(self, storage):
        assert await storage.get_approval(12345) is None

    async def test_set_approval_active(self, storage):
        approval_id = await storage.create_approval(1, "orig", "trans", [])
        await storage.set_approval_active(approval_id, "original", "orig")
        approval = await storage.get_approval(approval_id)
        assert approval.active_mode == "original"
        assert approval.active_text == "orig"

    @pytest.mark.parametrize("dest,attr", [("li", "li_enabled"), ("ig", "ig_enabled")])
    async def test_set_approval_dest(self, storage, dest, attr):
        approval_id = await storage.create_approval(1, "orig", "trans", [])
        await storage.set_approval_dest(approval_id, dest, False)
        assert getattr(await storage.get_approval(approval_id), attr) is False
        await storage.set_approval_dest(approval_id, dest, True)
        assert getattr(await storage.get_approval(approval_id), attr) is True

    async def test_delete(self, storage):
        approval_id = await storage.create_approval(1, "orig", "trans", [])
        await storage.delete_approval(approval_id)
        assert await storage.get_approval(approval_id) is None
