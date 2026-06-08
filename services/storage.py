import json
from pathlib import Path
from typing import Optional

import aiosqlite

from models import User, PendingPost


class Storage:
    def __init__(self, db_path: str = "data/bot.db"):
        self.db_path = db_path

    async def init(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    source_lang TEXT NOT NULL DEFAULT 'ru',
                    target_lang TEXT NOT NULL DEFAULT 'en',
                    linkedin_access_token TEXT,
                    linkedin_person_urn TEXT
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS pending_posts (
                    user_id INTEGER PRIMARY KEY,
                    original_text TEXT NOT NULL,
                    translated_text TEXT NOT NULL,
                    photo_file_ids TEXT NOT NULL DEFAULT '[]'
                )
                """
            )
            await db.commit()

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
                linkedin_access_token=row["linkedin_access_token"],
                linkedin_person_urn=row["linkedin_person_urn"],
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

    async def update_linkedin_token(self, user_id: int, access_token: str, person_urn: str) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE users SET linkedin_access_token = ?, linkedin_person_urn = ? WHERE user_id = ?",
                (access_token, person_urn, user_id),
            )
            await db.commit()

    async def save_pending_post(self, user_id: int, original_text: str, translated_text: str, photo_file_ids: list[str]) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO pending_posts (user_id, original_text, translated_text, photo_file_ids)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, original_text, translated_text, json.dumps(photo_file_ids)),
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
            )

    async def delete_pending_post(self, user_id: int) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM pending_posts WHERE user_id = ?", (user_id,))
            await db.commit()
