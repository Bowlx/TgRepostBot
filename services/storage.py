import json
from pathlib import Path
from typing import Optional

import aiosqlite

from models import User, PendingPost, Approval


class Storage:
    def __init__(self, db_path: str = "data/bot.db"):
        self.db_path = db_path

    async def init(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    source_lang TEXT NOT NULL DEFAULT 'ru',
                    target_lang TEXT NOT NULL DEFAULT 'en',
                    translate_enabled INTEGER NOT NULL DEFAULT 1,
                    approve_enabled INTEGER NOT NULL DEFAULT 0,
                    linkedin_access_token TEXT,
                    linkedin_person_urn TEXT,
                    linkedin_enabled INTEGER NOT NULL DEFAULT 1,
                    instagram_username TEXT,
                    instagram_password_encrypted TEXT,
                    instagram_totp_secret_encrypted TEXT,
                    instagram_sessionid_encrypted TEXT,
                    instagram_enabled INTEGER NOT NULL DEFAULT 1
                )
                """
            )
            # Migrations: add columns for existing databases (idempotent).
            migration_cols = [
                ("translate_enabled", "INTEGER NOT NULL DEFAULT 1"),
                ("approve_enabled", "INTEGER NOT NULL DEFAULT 0"),
                ("linkedin_enabled", "INTEGER NOT NULL DEFAULT 1"),
                ("instagram_username", "TEXT"),
                ("instagram_password_encrypted", "TEXT"),
                ("instagram_totp_secret_encrypted", "TEXT"),
                ("instagram_sessionid_encrypted", "TEXT"),
                ("instagram_enabled", "INTEGER NOT NULL DEFAULT 1"),
            ]
            for col, decl in migration_cols:
                try:
                    await db.execute(f"ALTER TABLE users ADD COLUMN {col} {decl}")
                except aiosqlite.OperationalError:
                    pass  # Column already exists
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS pending_posts (
                    user_id INTEGER PRIMARY KEY,
                    original_text TEXT NOT NULL,
                    translated_text TEXT NOT NULL,
                    photo_file_ids TEXT NOT NULL DEFAULT '[]',
                    active_text TEXT NOT NULL DEFAULT '',
                    active_mode TEXT NOT NULL DEFAULT 'translated',
                    li_enabled INTEGER NOT NULL DEFAULT 1,
                    ig_enabled INTEGER NOT NULL DEFAULT 1
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS pending_approvals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    original_text TEXT NOT NULL,
                    translated_text TEXT NOT NULL,
                    photo_file_ids TEXT NOT NULL DEFAULT '[]',
                    active_text TEXT NOT NULL DEFAULT '',
                    active_mode TEXT NOT NULL DEFAULT 'translated',
                    li_enabled INTEGER NOT NULL DEFAULT 1,
                    ig_enabled INTEGER NOT NULL DEFAULT 1
                )
                """
            )
            # Migrations: add per-post columns to existing pending tables.
            for table in ("pending_posts", "pending_approvals"):
                for col, decl in [
                    ("active_text", "TEXT NOT NULL DEFAULT ''"),
                    ("active_mode", "TEXT NOT NULL DEFAULT 'translated'"),
                    ("li_enabled", "INTEGER NOT NULL DEFAULT 1"),
                    ("ig_enabled", "INTEGER NOT NULL DEFAULT 1"),
                ]:
                    try:
                        await db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
                    except aiosqlite.OperationalError:
                        pass
            await db.commit()

    # ── Global settings ──────────────────────────────────────

    async def get_setting(self, key: str) -> Optional[str]:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = await cursor.fetchone()
            return row[0] if row else None

    async def set_setting(self, key: str, value: str) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (key, value),
            )
            await db.commit()

    async def get_all_settings(self) -> dict[str, str]:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("SELECT key, value FROM settings")
            rows = await cursor.fetchall()
            return {row[0]: row[1] for row in rows}

    async def get_user(self, user_id: int) -> Optional[User]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM users WHERE user_id = ?", (user_id,)
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            return User(
                user_id=row["user_id"],
                source_lang=row["source_lang"],
                target_lang=row["target_lang"],
                translate_enabled=bool(row["translate_enabled"]),
                approve_enabled=bool(row["approve_enabled"]),
                linkedin_access_token=row["linkedin_access_token"],
                linkedin_person_urn=row["linkedin_person_urn"],
                linkedin_enabled=bool(row["linkedin_enabled"]),
                instagram_username=row["instagram_username"],
                instagram_password_encrypted=row["instagram_password_encrypted"],
                instagram_totp_secret_encrypted=row["instagram_totp_secret_encrypted"],
                instagram_sessionid_encrypted=row["instagram_sessionid_encrypted"],
                instagram_enabled=bool(row["instagram_enabled"]),
            )

    async def create_user(self, user_id: int, source_lang: str = "ru", target_lang: str = "en") -> User:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO users (user_id, source_lang, target_lang) VALUES (?, ?, ?)",
                (user_id, source_lang, target_lang),
            )
            await db.commit()
        return User(user_id=user_id, source_lang=source_lang, target_lang=target_lang)

    async def update_languages(self, user_id: int, source_lang: str, target_lang: str) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE users SET source_lang = ?, target_lang = ? WHERE user_id = ?",
                (source_lang, target_lang, user_id),
            )
            await db.commit()

    async def set_translate_enabled(self, user_id: int, enabled: bool) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE users SET translate_enabled = ? WHERE user_id = ?",
                (1 if enabled else 0, user_id),
            )
            await db.commit()

    async def set_approve_enabled(self, user_id: int, enabled: bool) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE users SET approve_enabled = ? WHERE user_id = ?",
                (1 if enabled else 0, user_id),
            )
            await db.commit()

    async def set_instagram_creds(
        self,
        user_id: int,
        username: str,
        enc_password: str,
        enc_totp: Optional[str] = None,
    ) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                UPDATE users
                SET instagram_username = ?,
                    instagram_password_encrypted = ?,
                    instagram_totp_secret_encrypted = ?,
                    instagram_sessionid_encrypted = NULL,
                    instagram_enabled = 1
                WHERE user_id = ?
                """,
                (username, enc_password, enc_totp, user_id),
            )
            await db.commit()

    async def set_instagram_sessionid(
        self,
        user_id: int,
        username: str,
        enc_sessionid: str,
    ) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                UPDATE users
                SET instagram_username = ?,
                    instagram_sessionid_encrypted = ?,
                    instagram_password_encrypted = NULL,
                    instagram_totp_secret_encrypted = NULL,
                    instagram_enabled = 1
                WHERE user_id = ?
                """,
                (username, enc_sessionid, user_id),
            )
            await db.commit()

    async def clear_instagram_creds(self, user_id: int) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                UPDATE users
                SET instagram_username = NULL,
                    instagram_password_encrypted = NULL,
                    instagram_totp_secret_encrypted = NULL,
                    instagram_sessionid_encrypted = NULL
                WHERE user_id = ?
                """,
                (user_id,),
            )
            await db.commit()

    async def set_linkedin_enabled(self, user_id: int, enabled: bool) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE users SET linkedin_enabled = ? WHERE user_id = ?",
                (1 if enabled else 0, user_id),
            )
            await db.commit()

    async def set_instagram_enabled(self, user_id: int, enabled: bool) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE users SET instagram_enabled = ? WHERE user_id = ?",
                (1 if enabled else 0, user_id),
            )
            await db.commit()

    async def update_linkedin_token(self, user_id: int, access_token: str, person_urn: str) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE users SET linkedin_access_token = ?, linkedin_person_urn = ? WHERE user_id = ?",
                (access_token, person_urn, user_id),
            )
            await db.commit()

    async def save_pending_post(self, user_id: int, original_text: str, translated_text: str, photo_file_ids: list[str], li_enabled: bool = True, ig_enabled: bool = True) -> None:
        # Default active text = the translated version (falls back to original if empty).
        active_text = translated_text or original_text
        active_mode = "translated" if (translated_text and translated_text != original_text) else "original"
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO pending_posts
                    (user_id, original_text, translated_text, photo_file_ids, active_text, active_mode, li_enabled, ig_enabled)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, original_text, translated_text, json.dumps(photo_file_ids), active_text, active_mode,
                 1 if li_enabled else 0, 1 if ig_enabled else 0),
            )
            await db.commit()

    async def get_pending_post(self, user_id: int) -> Optional[PendingPost]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM pending_posts WHERE user_id = ?", (user_id,)
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            return PendingPost(
                user_id=row["user_id"],
                original_text=row["original_text"],
                translated_text=row["translated_text"],
                photo_file_ids=json.loads(row["photo_file_ids"]),
                active_text=row["active_text"],
                active_mode=row["active_mode"],
                li_enabled=bool(row["li_enabled"]),
                ig_enabled=bool(row["ig_enabled"]),
            )

    async def delete_pending_post(self, user_id: int) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM pending_posts WHERE user_id = ?", (user_id,))
            await db.commit()

    async def get_all_active_users(self) -> list[User]:
        """Users with at least one connected destination (LinkedIn OR Instagram)."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT * FROM users
                WHERE linkedin_access_token IS NOT NULL
                   OR instagram_username IS NOT NULL
                """
            )
            rows = await cursor.fetchall()
            return [
                User(
                    user_id=row["user_id"],
                    source_lang=row["source_lang"],
                    target_lang=row["target_lang"],
                    translate_enabled=bool(row["translate_enabled"]),
                    approve_enabled=bool(row["approve_enabled"]),
                    linkedin_access_token=row["linkedin_access_token"],
                    linkedin_person_urn=row["linkedin_person_urn"],
                    linkedin_enabled=bool(row["linkedin_enabled"]),
                    instagram_username=row["instagram_username"],
                    instagram_password_encrypted=row["instagram_password_encrypted"],
                    instagram_totp_secret_encrypted=row["instagram_totp_secret_encrypted"],
                    instagram_sessionid_encrypted=row["instagram_sessionid_encrypted"],
                    instagram_enabled=bool(row["instagram_enabled"]),
                )
                for row in rows
            ]

    # ── Approval queue (auto-mode approval gate) ─────────────

    async def create_approval(
        self, user_id: int, original_text: str, translated_text: str, photo_file_ids: list[str], li_enabled: bool = True, ig_enabled: bool = True
    ) -> int:
        active_text = translated_text or original_text
        active_mode = "translated" if (translated_text and translated_text != original_text) else "original"
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO pending_approvals
                    (user_id, original_text, translated_text, photo_file_ids, active_text, active_mode, li_enabled, ig_enabled)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, original_text, translated_text, json.dumps(photo_file_ids), active_text, active_mode,
                 1 if li_enabled else 0, 1 if ig_enabled else 0),
            )
            await db.commit()
            return cursor.lastrowid

    async def get_approval(self, approval_id: int) -> Optional[Approval]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM pending_approvals WHERE id = ?", (approval_id,)
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            return Approval(
                id=row["id"],
                user_id=row["user_id"],
                original_text=row["original_text"],
                translated_text=row["translated_text"],
                photo_file_ids=json.loads(row["photo_file_ids"]),
                active_text=row["active_text"],
                active_mode=row["active_mode"],
                li_enabled=bool(row["li_enabled"]),
                ig_enabled=bool(row["ig_enabled"]),
            )

    async def set_pending_active(self, user_id: int, mode: str, text: str) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE pending_posts SET active_mode = ?, active_text = ? WHERE user_id = ?",
                (mode, text, user_id),
            )
            await db.commit()

    async def set_approval_active(self, approval_id: int, mode: str, text: str) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE pending_approvals SET active_mode = ?, active_text = ? WHERE id = ?",
                (mode, text, approval_id),
            )
            await db.commit()

    async def set_pending_dest(self, user_id: int, dest: str, enabled: bool) -> None:
        col = "li_enabled" if dest == "li" else "ig_enabled"
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                f"UPDATE pending_posts SET {col} = ? WHERE user_id = ?",
                (1 if enabled else 0, user_id),
            )
            await db.commit()

    async def set_approval_dest(self, approval_id: int, dest: str, enabled: bool) -> None:
        col = "li_enabled" if dest == "li" else "ig_enabled"
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                f"UPDATE pending_approvals SET {col} = ? WHERE id = ?",
                (1 if enabled else 0, approval_id),
            )
            await db.commit()

    async def update_approval_text(self, approval_id: int, translated_text: str) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE pending_approvals SET translated_text = ? WHERE id = ?",
                (translated_text, approval_id),
            )
            await db.commit()

    async def delete_approval(self, approval_id: int) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM pending_approvals WHERE id = ?", (approval_id,))
            await db.commit()
