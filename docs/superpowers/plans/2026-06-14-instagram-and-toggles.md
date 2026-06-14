# Instagram Destination + Destination Toggles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Instagram as a second publishing destination (via `instagrapi`, with TOTP + SMS/email 2FA) alongside LinkedIn, and add per-destination enable/disable toggles — all routed through a single publisher layer.

**Architecture:** A new `Publisher` service replaces the hard-coded LinkedIn publish blocks in `channel.py`/`post.py`/`approval.py`. It downloads photos once to temp files, then publishes to every connected+enabled destination. Instagram credentials (password + optional TOTP secret) are Fernet-encrypted at rest. `instagrapi` runs off-thread via `asyncio.to_thread`; SMS/email 2FA is bridged to an interactive Telegram FSM via an in-memory future registry.

**Tech Stack:** Python 3.12, aiogram 3, aiosqlite, instagrapi, cryptography (Fernet), pyotp (TOTP), Docker.

---

## File Structure

| File | Responsibility | New/Modified |
|------|---------------|:------------:|
| `requirements.txt` | Add instagrapi, cryptography, pyotp | Modify |
| `config.py` | Add `encryption_key` setting | Modify |
| `.env.example` | Document `ENCRYPTION_KEY` | Modify |
| `services/crypto.py` | Fernet encrypt/decrypt | **New** |
| `services/instagram.py` | instagrapi client: login (TOTP+challenge), publish, logout | **New** |
| `services/publisher.py` | `publish_to_all` — routes to LinkedIn + Instagram | **New** |
| `models.py` | User gains IG fields + enable toggles | Modify |
| `services/storage.py` | New columns, migrations, IG/toggle methods, `get_all_active_users` | Modify |
| `bot/handlers/instagram.py` | `/iglogin`, `/iglogout`, 2FA code FSM | **New** |
| `bot/handlers/settings.py` | `/linkedin`, `/instagram`, `/destinations` | Modify |
| `bot/handlers/channel.py` | Use Publisher instead of `publish_to_linkedin` | Modify |
| `bot/handlers/post.py` | Use Publisher | Modify |
| `bot/handlers/approval.py` | Use Publisher for the publish action | Modify |
| `bot/handlers/start.py` | Status shows both destinations | Modify |
| `bot/main.py` | Wire crypto, instagram, publisher; register instagram router | Modify |
| `README.md` | Document Instagram setup + toggles | Modify |

---

### Task 1: Dependencies and config

**Files:**
- Modify: `requirements.txt`
- Modify: `config.py`
- Modify: `.env.example`

- [ ] **Step 1: Update requirements.txt**

```
aiogram>=3.15,<4
aiosqlite
pydantic-settings
python-dotenv
deep-translator
instagrapi
cryptography
pyotp
```

- [ ] **Step 2: Update config.py** — add the required encryption key.

```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    bot_token: str
    encryption_key: str
    database_path: str = "data/bot.db"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 3: Update .env.example** — document the new key (show how to generate one).

```
# Bot token from @BotFather
BOT_TOKEN=your_telegram_bot_token

# Fernet key for encrypting Instagram credentials.
# Generate one with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
ENCRYPTION_KEY=paste_generated_fernet_key_here

# DATABASE_PATH=data/bot.db
```

- [ ] **Step 4: Verify import**

Run: `python -c "from config import Settings"`
Expected: no error (pydantic-settings already installed).

- [ ] **Step 5: Commit**

```bash
git add requirements.txt config.py .env.example
git commit -m "feat: add instagrapi, cryptography, pyotp deps + ENCRYPTION_KEY config"
```

---

### Task 2: Crypto service (Fernet)

**Files:**
- Create: `services/crypto.py`

- [ ] **Step 1: Write services/crypto.py**

```python
from cryptography.fernet import Fernet


class Crypto:
    """Symmetric encryption (Fernet) for secrets stored at rest.

    Used for the Instagram password and optional TOTP secret. The key comes
    from ENCRYPTION_KEY in .env; without it the bot refuses to start.
    """

    def __init__(self, key: str):
        # Raises if the key is malformed — surfaces at startup, not at use.
        self._fernet = Fernet(key.encode() if isinstance(key, str) else key)

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, token: str) -> str:
        return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")
```

- [ ] **Step 2: Verify it round-trips**

Run:
```bash
python -c "
from services.crypto import Crypto
from cryptography.fernet import Fernet
k = Fernet.generate_key().decode()
c = Crypto(k)
enc = c.encrypt('hunter2')
assert enc != 'hunter2'
assert c.decrypt(enc) == 'hunter2'
print('crypto OK')
"
```
Expected: `crypto OK`

- [ ] **Step 3: Commit**

```bash
git add services/crypto.py
git commit -m "feat: add Fernet crypto service for secrets at rest"
```

---

### Task 3: User model + storage changes

**Files:**
- Modify: `models.py`
- Modify: `services/storage.py`

- [ ] **Step 1: Extend the User dataclass** — add IG credentials + per-destination toggles.

```python
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class User:
    user_id: int
    source_lang: str = "ru"
    target_lang: str = "en"
    translate_enabled: bool = True
    approve_enabled: bool = False
    linkedin_access_token: Optional[str] = None
    linkedin_person_urn: Optional[str] = None
    linkedin_enabled: bool = True
    instagram_username: Optional[str] = None
    instagram_password_encrypted: Optional[str] = None
    instagram_totp_secret_encrypted: Optional[str] = None
    instagram_enabled: bool = True


@dataclass
class PendingPost:
    user_id: int
    original_text: str
    translated_text: str
    photo_file_ids: list[str] = field(default_factory=list)


@dataclass
class Approval:
    id: int
    user_id: int
    original_text: str
    translated_text: str
    photo_file_ids: list[str] = field(default_factory=list)
```

- [ ] **Step 2: Update the users CREATE TABLE + migrations in storage.py**

Replace the `CREATE TABLE users` block AND the migration loop in `Storage.init` with:

```python
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
                ("instagram_enabled", "INTEGER NOT NULL DEFAULT 1"),
            ]
            for col, decl in migration_cols:
                try:
                    await db.execute(f"ALTER TABLE users ADD COLUMN {col} {decl}")
                except aiosqlite.OperationalError:
                    pass  # Column already exists
```

- [ ] **Step 3: Update get_user to read the new columns**

Replace the body of `get_user` (the `return User(...)` block) with:

```python
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
                instagram_enabled=bool(row["instagram_enabled"]),
            )
```

- [ ] **Step 4: Replace get_all_linkedin_users with get_all_active_users**

Rename and broaden the query — a user is a "publisher" if they have ANY connected destination:

```python
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
                    instagram_enabled=bool(row["instagram_enabled"]),
                )
                for row in rows
            ]
```

- [ ] **Step 5: Add Instagram-credential and toggle methods**

Append after `set_approve_enabled`:

```python
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
                    instagram_enabled = 1
                WHERE user_id = ?
                """,
                (username, enc_password, enc_totp, user_id),
            )
            await db.commit()

    async def clear_instagram_creds(self, user_id: int) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                UPDATE users
                SET instagram_username = NULL,
                    instagram_password_encrypted = NULL,
                    instagram_totp_secret_encrypted = NULL
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
```

- [ ] **Step 6: Verify storage imports**

Run: `python -c "from services.storage import Storage; from models import User; print('OK')"`
Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git add models.py services/storage.py
git commit -m "feat: user model + storage for Instagram creds and destination toggles"
```

---

### Task 4: Instagram client (instagrapi)

**Files:**
- Create: `services/instagram.py`

- [ ] **Step 1: Write services/instagram.py**

```python
"""Instagram destination via the instagrapi private-API library.

instagrapi is synchronous, so every call runs in asyncio.to_thread. Login
supports TOTP (automatic, via pyotp) and SMS/email challenges (interactive —
bridged to a Telegram FSM through an in-memory future registry).
"""
import asyncio
import logging
import os
from typing import Optional

import pyotp
from instagrapi import Client

from services.crypto import Crypto

logger = logging.getLogger(__name__)


class InstagramClient:
    def __init__(
        self,
        session_dir: str,
        crypto: Crypto,
        ask_code=None,
    ):
        # ask_code: async callable(user_id, choice) -> Optional[str]
        # provided by the handler layer to request an SMS/email 2FA code.
        self.session_dir = session_dir
        self.crypto = crypto
        self.ask_code = ask_code
        # user_id -> asyncio.Future, resolved when the FSM receives the code.
        self._pending_codes: dict[int, asyncio.Future] = {}
        os.makedirs(session_dir, exist_ok=True)

    def session_path(self, user_id: int) -> str:
        return os.path.join(self.session_dir, f"ig_session_{user_id}.json")

    def submit_code(self, user_id: int, code: str) -> bool:
        """Called by the FSM handler when the user types their 2FA code."""
        fut = self._pending_codes.get(user_id)
        if fut is None or fut.done():
            return False
        fut.set_result(code)
        return True

    async def login(
        self,
        user_id: int,
        username: str,
        password: str,
        totp_secret: Optional[str] = None,
    ) -> None:
        loop = asyncio.get_running_loop()

        def challenge_handler(uname: str, choice) -> str:
            # Runs inside the worker thread. Bridge to the async ask_code.
            if self.ask_code is None:
                return False
            fut: asyncio.Future = loop.create_future()
            self._pending_codes[user_id] = fut
            try:
                return asyncio.run_coroutine_threadsafe(
                    self.ask_code(user_id, choice), loop
                ).result(timeout=300)
            except Exception as e:
                logger.error(f"Instagram challenge code not provided: {e}")
                return False
            finally:
                self._pending_codes.pop(user_id, None)

        def _do_login():
            cl = Client()
            cl.challenge_code_handler = challenge_handler
            path = self.session_path(user_id)
            if os.path.exists(path):
                cl.set_settings(cl.load_settings(path))
            verification = pyotp.TOTP(totp_secret).now() if totp_secret else None
            cl.login(username, password, verification_code=verification)
            cl.dump_settings(path)

        try:
            await asyncio.to_thread(_do_login)
        except Exception as e:
            self._pending_codes.pop(user_id, None)
            raise

    async def _get_client(self, user_id: int, username: str, password: str,
                          totp_secret: Optional[str]) -> Client:
        """Load a logged-in client, reusing the session file (re-login on expiry)."""
        loop = asyncio.get_running_loop()

        def challenge_handler(uname, choice):
            if self.ask_code is None:
                return False
            fut = loop.create_future()
            self._pending_codes[user_id] = fut
            try:
                return asyncio.run_coroutine_threadsafe(
                    self.ask_code(user_id, choice), loop
                ).result(timeout=300)
            except Exception:
                return False
            finally:
                self._pending_codes.pop(user_id, None)

        def _build():
            cl = Client()
            cl.challenge_code_handler = challenge_handler
            path = self.session_path(user_id)
            if os.path.exists(path):
                cl.set_settings(cl.load_settings(path))
            verification = pyotp.TOTP(totp_secret).now() if totp_secret else None
            cl.login(username, password, verification_code=verification)
            return cl

        return await asyncio.to_thread(_build)

    async def publish(
        self,
        user_id: int,
        username: str,
        password_enc: str,
        totp_secret_enc: Optional[str],
        caption: str,
        image_paths: list[str],
    ) -> str:
        """Publish a photo or carousel. Returns the media id (str)."""
        password = self.crypto.decrypt(password_enc)
        totp_secret = (
            self.crypto.decrypt(totp_secret_enc) if totp_secret_enc else None
        )

        cl = await self._get_client(user_id, username, password, totp_secret)

        def _upload():
            if len(image_paths) == 1:
                media = cl.photo_upload(image_paths[0], caption)
            else:
                media = cl.album_upload(image_paths, caption)
            return str(media.id)

        try:
            return await asyncio.to_thread(_upload)
        except Exception:
            # One retry: rebuild client (forces fresh login) then upload again.
            logger.warning("Instagram publish failed once, retrying after re-login")
            cl = await self._get_client(user_id, username, password, totp_secret)
            return await asyncio.to_thread(_upload)

    async def logout(self, user_id: int) -> None:
        path = self.session_path(user_id)
        if os.path.exists(path):
            os.remove(path)
```

- [ ] **Step 2: Verify import**

Run: `python -c "from services.instagram import InstagramClient; print('OK')"`
Expected: `OK` (requires instagrapi installed — `pip install instagrapi`).

- [ ] **Step 3: Commit**

```bash
git add services/instagram.py
git commit -m "feat: Instagram client (instagrapi) with TOTP + interactive 2FA"
```

---

### Task 5: Publisher service

**Files:**
- Create: `services/publisher.py`

- [ ] **Step 1: Write services/publisher.py**

```python
"""Single entry point that fans a post out to every connected+enabled destination."""
import logging
import os
import tempfile
from dataclasses import dataclass
from typing import Optional

from aiogram import Bot

from models import User
from services.linkedin import LinkedInClient
from services.instagram import InstagramClient

logger = logging.getLogger(__name__)


@dataclass
class DestResult:
    name: str   # "LinkedIn" / "Instagram"
    ok: bool
    detail: str

    @property
    def icon(self) -> str:
        if not self.ok:
            return "❌"
        return "✅"


class Publisher:
    def __init__(self, linkedin: LinkedInClient, instagram: InstagramClient, bot: Bot):
        self.linkedin = linkedin
        self.instagram = instagram
        self.bot = bot

    async def publish_to_all(
        self,
        user: User,
        text: str,
        photo_file_ids: list[str],
    ) -> list[DestResult]:
        results: list[DestResult] = []

        # Download each photo to a temp file ONCE; both destinations reuse the paths.
        temp_paths = await self._download_photos(photo_file_ids)
        try:
            results.append(await self._publish_linkedin(user, text, temp_paths))
            results.append(await self._publish_instagram(user, text, temp_paths))
        finally:
            for path in temp_paths:
                try:
                    os.remove(path)
                except OSError:
                    pass
        return results

    async def _download_photos(self, photo_file_ids: list[str]) -> list[str]:
        paths: list[str] = []
        for file_id in photo_file_ids:
            try:
                file = await self.bot.get_file(file_id)
                downloaded = await self.bot.download_file(file.file_path)
                data = downloaded.read()
                suffix = ".jpg"
                fd, path = tempfile.mkstemp(suffix=suffix)
                with os.fdopen(fd, "wb") as f:
                    f.write(data)
                paths.append(path)
            except Exception as e:
                logger.error(f"Failed to download photo {file_id}: {e}")
        return paths

    async def _publish_linkedin(
        self, user: User, text: str, photo_paths: list[str]
    ) -> DestResult:
        if not user.linkedin_access_token or not user.linkedin_person_urn:
            return DestResult("LinkedIn", False, "не подключён")
        if not user.linkedin_enabled:
            return DestResult("LinkedIn", True, "⏸ выключен")

        image_urns: list[str] = []
        for path in photo_paths:
            try:
                with open(path, "rb") as f:
                    data = f.read()
                urn = await self.linkedin.upload_image_full(
                    user.linkedin_access_token, user.linkedin_person_urn, data
                )
                image_urns.append(urn)
            except Exception as e:
                logger.error(f"LinkedIn image upload failed: {e}")
        try:
            await self.linkedin.create_post(
                user.linkedin_access_token,
                user.linkedin_person_urn,
                text,
                image_urns or None,
            )
            return DestResult("LinkedIn", True, "опубликован")
        except Exception as e:
            return DestResult("LinkedIn", False, str(e))

    async def _publish_instagram(
        self, user: User, text: str, photo_paths: list[str]
    ) -> DestResult:
        if not user.instagram_username or not user.instagram_password_encrypted:
            return DestResult("Instagram", False, "не подключён")
        if not user.instagram_enabled:
            return DestResult("Instagram", True, "⏸ выключен")
        if not photo_paths:
            # Instagram has no text-only posts — skip gracefully.
            return DestResult("Instagram", False, "нет фото (Instagram требует медиа)")

        try:
            media_id = await self.instagram.publish(
                user.user_id,
                user.instagram_username,
                user.instagram_password_encrypted,
                user.instagram_totp_secret_encrypted,
                text,
                photo_paths,
            )
            return DestResult("Instagram", True, f"опубликован ({media_id})")
        except Exception as e:
            return DestResult("Instagram", False, str(e))


def render_results(results: list[DestResult]) -> str:
    lines = []
    for r in results:
        lines.append(f"{r.icon} {r.name}: {r.detail}")
    return "\n".join(lines)
```

- [ ] **Step 2: Verify import**

Run: `python -c "from services.publisher import Publisher, DestResult; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add services/publisher.py
git commit -m "feat: Publisher service — fans posts out to all destinations"
```

---

### Task 6: Instagram handler (/iglogin, /iglogout, 2FA FSM)

**Files:**
- Create: `bot/handlers/instagram.py`

- [ ] **Step 1: Write bot/handlers/instagram.py**

```python
"""Instagram connect/disconnect commands and the SMS/email 2FA code FSM.

The /iglogin message is deleted immediately so the password never lingers in
chat history. If a login triggers an SMS/email challenge, the instagrapi
challenge handler calls ask_code(), which prompts the user and waits on the
InstagramClient's pending-code future; the FSM handler below resolves it.
"""
import asyncio
import logging

from aiogram import Router, types, Bot, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from services.crypto import Crypto
from services.instagram import InstagramClient
from services.storage import Storage

router = Router()
logger = logging.getLogger(__name__)


class IgChallenge(StatesGroup):
    waiting_code = State()


async def _ask_code_factory(bot: Bot, instagram: InstagramClient, storage: Storage):
    """Builds the async ask_code callback the InstagramClient uses for 2FA."""
    async def ask_code(user_id: int, choice) -> str | None:
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        instagram._pending_codes[user_id] = fut
        try:
            await bot.send_message(
                user_id,
                "🔐 Instagram запросил код подтверждения (SMS/email).\n"
                "Отправьте код сюда в течение 5 минут:",
            )
            return await asyncio.wait_for(fut, timeout=300)
        except asyncio.TimeoutError:
            return None
        finally:
            instagram._pending_codes.pop(user_id, None)
    return ask_code


@router.message(F.text.startswith("/iglogin"))
async def cmd_iglogin(
    message: types.Message,
    bot: Bot,
    storage: Storage,
    instagram_client: InstagramClient,
    crypto: Crypto,
) -> None:
    # /iglogin <username> <password> [totp_secret]
    parts = message.text.split(maxsplit=3)
    if len(parts) < 3:
        await message.answer(
            "❌ Использование: <code>/iglogin логин пароль [totp_секрет]</code>\n\n"
            "TOTP-секрет — опционально, только если включена 2FA через приложение "
            "(Authenticator). Это base32-секрет из QR-кода."
        )
        return

    username = parts[1]
    password = parts[2]
    totp_secret = parts[3].strip() if len(parts) == 4 else None

    # Delete the message so the password doesn't stay in chat history.
    try:
        await message.delete()
    except Exception:
        pass

    # Ensure the user exists.
    if await storage.get_user(message.from_user.id) is None:
        await storage.create_user(message.from_user.id)

    status = await bot.send_message(message.from_user.id, "⏳ Вхожу в Instagram...")

    # Wire up the interactive 2FA code prompt.
    instagram_client.ask_code = await _ask_code_factory(bot, instagram_client, storage)

    try:
        await instagram_client.login(message.from_user.id, username, password, totp_secret)
    except Exception as e:
        logger.error(f"Instagram login failed: {e}")
        await status.edit_text(f"❌ Ошибка входа в Instagram: {e}")
        return

    enc_password = crypto.encrypt(password)
    enc_totp = crypto.encrypt(totp_secret) if totp_secret else None
    await storage.set_instagram_creds(message.from_user.id, username, enc_password, enc_totp)
    await status.edit_text(
        f"✅ Instagram подключён: <b>@{username}</b>\n"
        f"Публикация включена. Выключить: <code>/instagram off</code>"
    )


@router.message(F.text.startswith("/iglogout"))
async def cmd_iglogout(
    message: types.Message,
    storage: Storage,
    instagram_client: InstagramClient,
) -> None:
    user = await storage.get_user(message.from_user.id)
    if user is None or not user.instagram_username:
        await message.answer("Instagram не подключён.")
        return
    await instagram_client.logout(message.from_user.id)
    await storage.clear_instagram_creds(message.from_user.id)
    await message.answer("✅ Instagram отключён (креды и сессия удалены).")


# ── 2FA code FSM handler ───────────────────────────────────

@router.message(IgChallenge.waiting_code, F.text)
async def receive_ig_code(message: types.Message, instagram_client: InstagramClient) -> None:
    code = message.text.strip()
    # The pending future lives on the client; resolve it so ask_code() unblocks.
    delivered = instagram_client.submit_code(message.from_user.id, code)
    if delivered:
        await message.answer("Код передан, продолжаю вход...")
    else:
        await message.answer("⚠️ Запрос кода уже не активен. Попробуйте /iglogin снова.")
```

- [ ] **Step 2: Verify import**

Run: `python -c "from bot.handlers.instagram import router; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add bot/handlers/instagram.py
git commit -m "feat: /iglogin + /iglogout handlers with interactive 2FA FSM"
```

---

### Task 7: Toggle commands (/linkedin, /instagram, /destinations)

**Files:**
- Modify: `bot/handlers/settings.py`

- [ ] **Step 1: Add toggle + status commands**

Append these handlers at the end of `bot/handlers/settings.py` (keep all existing handlers intact):

```python


def _parse_on_off(text: str) -> bool | None:
    parts = text.split()
    if len(parts) != 2:
        return None
    return parts[1].lower() in ("on", "вкл")


@router.message(Command("linkedin"))
async def cmd_linkedin_toggle(message: types.Message, storage: Storage) -> None:
    enabled = _parse_on_off(message.text)
    if enabled is None:
        await message.answer(
            "❌ Использование: <code>/linkedin on</code> или <code>/linkedin off</code>\n\n"
            "Пауза публикации в LinkedIn без отключения аккаунта."
        )
        return
    await storage.set_linkedin_enabled(message.from_user.id, enabled)
    await message.answer(
        f"✅ LinkedIn: <b>{'включён' if enabled else 'пауза'}</b>."
    )


@router.message(Command("instagram"))
async def cmd_instagram_toggle(message: types.Message, storage: Storage) -> None:
    enabled = _parse_on_off(message.text)
    if enabled is None:
        await message.answer(
            "❌ Использование: <code>/instagram on</code> или <code>/instagram off</code>"
        )
        return
    await storage.set_instagram_enabled(message.from_user.id, enabled)
    await message.answer(
        f"✅ Instagram: <b>{'включён' if enabled else 'пауза'}</b>."
    )


@router.message(Command("destinations"))
async def cmd_destinations(message: types.Message, storage: Storage) -> None:
    user = await storage.get_user(message.from_user.id)
    if user is None:
        await message.answer("Сначала нажмите /start")
        return

    def line(name: str, connected: bool, enabled: bool) -> str:
        if not connected:
            return f"  ⚪️ {name}: не подключён"
        return f"  {'🟢' if enabled else '⏸️'} {name}: {'включён' if enabled else 'пауза'}"

    await message.answer(
        "<b>📍 Куда публикуем:</b>\n"
        + line("LinkedIn", bool(user.linkedin_access_token), user.linkedin_enabled)
        + "\n"
        + line("Instagram", bool(user.instagram_username), user.instagram_enabled)
        + "\n\nПереключить: <code>/linkedin on|off</code> или <code>/instagram on|off</code>"
    )
```

- [ ] **Step 2: Verify import**

Run: `python -c "from bot.handlers.settings import router; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add bot/handlers/settings.py
git commit -m "feat: /linkedin, /instagram toggles + /destinations status"
```

---

### Task 8: Wire main.py (crypto, instagram, publisher, router, middleware)

**Files:**
- Modify: `bot/main.py`

- [ ] **Step 1: Replace bot/main.py**

```python
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.handlers import start, settings, channel, forward, post, setup, approval, instagram
from config import get_settings
from services.storage import Storage
from services.translator import Translator
from services.linkedin import LinkedInClient
from services.crypto import Crypto
from services.instagram import InstagramClient
from services.publisher import Publisher

logger = logging.getLogger(__name__)


async def service_middleware(handler, event, data):
    dp = data["dispatcher"]
    data["storage"] = dp["storage"]
    data["translator"] = dp["translator"]
    data["linkedin_client"] = dp["linkedin"]
    data["instagram_client"] = dp["instagram"]
    data["publisher"] = dp["publisher"]
    data["crypto"] = dp["crypto"]
    data["app_config"] = dp["config"]
    return await handler(event, data)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)

    cfg = get_settings()

    storage = Storage(db_path=cfg.database_path)
    await storage.init()

    translator = Translator(storage=storage)
    linkedin = LinkedInClient(storage=storage)
    crypto = Crypto(cfg.encryption_key)
    instagram = InstagramClient(session_dir="data", crypto=crypto)
    publisher = Publisher(linkedin=linkedin, instagram=instagram, bot=None)

    bot = Bot(token=cfg.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    publisher.bot = bot  # bot is needed at publish time

    dp = Dispatcher()
    dp["storage"] = storage
    dp["translator"] = translator
    dp["linkedin"] = linkedin
    dp["instagram"] = instagram
    dp["publisher"] = publisher
    dp["crypto"] = crypto
    dp["config"] = cfg

    dp.update.middleware(service_middleware)

    dp.include_router(setup.router)
    dp.include_router(start.router)
    dp.include_router(settings.router)
    dp.include_router(instagram.router)
    dp.include_router(approval.router)
    dp.include_router(channel.router)
    dp.include_router(forward.router)
    dp.include_router(post.router)

    logger.info("Bot starting...")
    await dp.start_polling(bot)
```

Note: `Publisher` takes `bot=None` at construction and is assigned the real `Bot` once created — `Bot` requires the token and is built right after. This avoids a circular ordering problem.

- [ ] **Step 2: Verify import**

Run: `python -c "from bot.main import main; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add bot/main.py
git commit -m "feat: wire crypto, instagram, publisher into dispatcher + middleware"
```

---

### Task 9: Refactor channel.py to use the Publisher

**Files:**
- Modify: `bot/handlers/channel.py`

- [ ] **Step 1: Replace bot/handlers/channel.py**

The handler now fetches all active users (LinkedIn OR Instagram), and for each either auto-publishes via the Publisher or queues an approval. The old `publish_to_linkedin` helper is removed.

```python
import logging

from aiogram import Router, types, Bot, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from bot.media_group import MediaGroupAggregator, extract_group_content
from bot.text_format import format_text
from services.storage import Storage
from services.translator import Translator
from services.publisher import Publisher

router = Router()
logger = logging.getLogger(__name__)

aggregator = MediaGroupAggregator(delay=1.0)

router.channel_post.filter(F.chat.type == "channel")


def approval_keyboard(approval_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Опубликовать", callback_data=f"apv:{approval_id}:pub"),
                InlineKeyboardButton(text="✏️ Изменить", callback_data=f"apv:{approval_id}:edit"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"apv:{approval_id}:skip"),
            ]
        ]
    )


@router.channel_post(F.text | F.photo)
async def handle_channel_post(
    message: types.Message,
    bot: Bot,
    storage: Storage,
    translator: Translator,
    publisher: Publisher,
) -> None:
    """Buffer album messages, then publish the whole group as ONE post
    (immediately, or via an approval message if /approve on)."""

    async def publish_group(messages: list[types.Message]) -> None:
        original_text, photo_file_ids = extract_group_content(messages)
        if not original_text and not photo_file_ids:
            return

        users = await storage.get_all_active_users()
        if not users:
            logger.warning("No users with a connected destination, skipping channel post")
            return

        for user in users:
            text = original_text
            if original_text.strip() and user.translate_enabled:
                try:
                    text = await translator.translate(
                        original_text, user.source_lang, user.target_lang
                    )
                except Exception as e:
                    logger.error(f"Translation failed for user {user.user_id}: {e}")
            text = format_text(text)

            if user.approve_enabled:
                approval_id = await storage.create_approval(
                    user.user_id, original_text, text, photo_file_ids
                )
                preview = f"🆕 <b>Новый пост из канала</b>\n\n{text}\n\n"
                if photo_file_ids:
                    preview += f"🖼️ Изображений: {len(photo_file_ids)} шт.\n\n"
                preview += "Подтвердите публикацию:"
                try:
                    await bot.send_message(
                        user.user_id, preview, reply_markup=approval_keyboard(approval_id)
                    )
                except Exception as e:
                    logger.error(f"Failed to send approval DM to {user.user_id}: {e}")
                    await storage.delete_approval(approval_id)
            else:
                results = await publisher.publish_to_all(user, text, photo_file_ids)
                from services.publisher import render_results
                try:
                    await bot.send_message(
                        user.user_id,
                        "📋 <b>Опубликовано:</b>\n" + render_results(results),
                    )
                except Exception:
                    pass

    await aggregator.add(message, publish_group)
```

- [ ] **Step 2: Verify import**

Run: `python -c "from bot.handlers.channel import router; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add bot/handlers/channel.py
git commit -m "refactor: channel handler routes through Publisher (all destinations)"
```

---

### Task 10: Refactor post.py to use the Publisher

**Files:**
- Modify: `bot/handlers/post.py`

- [ ] **Step 1: Replace the /post handler body**

Replace the whole `bot/handlers/post.py` with:

```python
import logging

from aiogram import Router, types, Bot
from aiogram.filters import Command

from services.storage import Storage
from services.publisher import Publisher, render_results

router = Router()
logger = logging.getLogger(__name__)


@router.message(Command("preview"))
async def cmd_preview(message: types.Message, storage: Storage) -> None:
    pending = await storage.get_pending_post(message.from_user.id)
    if pending is None:
        await message.answer("❌ Нет отложенного поста. Перешлите сообщение боту.")
        return

    text = (
        f"<b>📋 Оригинал:</b>\n{pending.original_text}\n\n"
        f"<b>🌐 Перевод:</b>\n{pending.translated_text}\n\n"
    )
    if pending.photo_file_ids:
        text += f"🖼️ Изображений: {len(pending.photo_file_ids)} шт.\n\n"
    text += "<code>/post</code> — опубликовать\n<code>/skip</code> — отменить"
    await message.answer(text)


@router.message(Command("post"))
async def cmd_post(
    message: types.Message,
    bot: Bot,
    storage: Storage,
    publisher: Publisher,
) -> None:
    pending = await storage.get_pending_post(message.from_user.id)
    if pending is None:
        await message.answer("❌ Нет отложенного поста. Перешлите сообщение боту.")
        return

    user = await storage.get_user(message.from_user.id)
    connected = (
        user is not None
        and (user.linkedin_access_token or user.instagram_username)
    )
    if not connected:
        await message.answer("❌ Нет подключённых destination. Используйте /auth или /iglogin")
        return

    await message.answer("⏳ Публикую...")

    results = await publisher.publish_to_all(
        user, pending.translated_text, pending.photo_file_ids
    )

    if any(r.ok for r in results):
        await storage.delete_pending_post(message.from_user.id)
        await message.answer("✅ Готово!\n" + render_results(results))
    else:
        await message.answer(
            "❌ Ни один destination не сработал:\n" + render_results(results)
        )


@router.message(Command("skip"))
async def cmd_skip(message: types.Message, storage: Storage) -> None:
    deleted = await storage.get_pending_post(message.from_user.id)
    if deleted is None:
        await message.answer("❌ Нет отложенного поста для отмены.")
        return
    await storage.delete_pending_post(message.from_user.id)
    await message.answer("🗑️ Пост отменён.")
```

- [ ] **Step 2: Verify import**

Run: `python -c "from bot.handlers.post import router; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add bot/handlers/post.py
git commit -m "refactor: /post routes through Publisher"
```

---

### Task 11: Refactor approval.py to use the Publisher

**Files:**
- Modify: `bot/handlers/approval.py`

- [ ] **Step 1: Replace the _publish helper and its signature**

In `bot/handlers/approval.py`:

1. Change the imports — replace `from services.linkedin import LinkedInClient` with the publisher import:

```python
from services.publisher import Publisher, render_results
```

2. Change the `handle_approval_callback` signature: replace the `linkedin_client: LinkedInClient` parameter with `publisher: Publisher`, and update the `pub` branch call from `await _publish(callback, bot, storage, linkedin_client, approval)` to `await _publish(callback, bot, storage, publisher, approval)`.

3. Replace the whole `_publish` function with:

```python
async def _publish(callback, bot, storage, publisher: Publisher, approval) -> None:
    await callback.message.edit_text("⏳ Публикую...")
    user = await storage.get_user(approval.user_id)
    if user is None:
        await callback.message.edit_text("❌ Пользователь не найден.")
        await callback.answer()
        return
    results = await publisher.publish_to_all(
        user, approval.translated_text, approval.photo_file_ids
    )
    if any(r.ok for r in results):
        await storage.delete_approval(approval.id)
        await callback.message.edit_text("✅ Готово!\n" + render_results(results))
    else:
        await callback.message.edit_text(
            "❌ Ни один destination не сработал:\n" + render_results(results)
        )
    await callback.answer()
```

- [ ] **Step 2: Verify import**

Run: `python -c "from bot.handlers.approval import router; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add bot/handlers/approval.py
git commit -m "refactor: approval publish routes through Publisher"
```

---

### Task 12: Update start.py status block

**Files:**
- Modify: `bot/handlers/start.py`

- [ ] **Step 1: Update the status block + commands list**

In `cmd_start`, replace the `<b>📋 Статус:</b>…` block (the LinkedIn-only status) with a two-destination status, and add the new commands to the help text. Replace this section:

```python
        f"🌐 Переводчик: MyMemory ✅\n"
        f"🆔 LinkedIn App: ✅\n"
        f"💼 LinkedIn аккаунт: {'✅ Подключён' if has_linkedin_auth else '❌ Не подключён'}\n"
        f"🔤 Перевод: {'✅ вкл' if user.translate_enabled else '⏸ off'} ({user.source_lang} → {user.target_lang})\n"
        f"🔔 Подтверждение постов: {'✅ вкл' if user.approve_enabled else '⏸ off'}\n\n"
```

with:

```python
        f"🌐 Переводчик: Google ✅\n"
        f"💼 LinkedIn: {'✅ ' + ('вкл' if user.linkedin_enabled else 'пауза') if has_linkedin_app else '❌ не настроен'}\n"
        f"📸 Instagram: {'✅ ' + ('вкл' if user.instagram_enabled else 'пауза') if user.instagram_username else '❌ /iglogin'}\n"
        f"🔤 Перевод: {'✅ вкл' if user.translate_enabled else '⏸ off'} ({user.source_lang} → {user.target_lang})\n"
        f"🔔 Подтверждение постов: {'✅ вкл' if user.approve_enabled else '⏸ off'}\n\n"
```

And replace the existing commands help block:

```python
        welcome += (
            "<b>Команды:</b>\n"
            "• Перешлите пост — перевод + превью\n"
            "• <code>/post</code> — опубликовать\n"
            "• <code>/setlang ru en</code> — сменить языки\n"
            "• <code>/translate off</code> — отключить перевод\n"
            "• <code>/approve on</code> — подтверждение постов перед публикацией\n"
            "• <code>/setemail ваш@email</code> — поднять лимит переводов\n"
            "• <code>/setup</code> — перенастроить LinkedIn"
        )
```

with:

```python
        welcome += (
            "<b>Команды:</b>\n"
            "• Перешлите пост — перевод + превью\n"
            "• <code>/post</code> — опубликовать во все destination\n"
            "• <code>/iglogin логин пароль [totp]</code> — подключить Instagram\n"
            "• <code>/linkedin on|off</code> · <code>/instagram on|off</code> — пауза\n"
            "• <code>/destinations</code> — статус куда публикуем\n"
            "• <code>/setlang ru en</code> · <code>/translate off</code>\n"
            "• <code>/approve on</code> — подтверждение постов\n"
            "• <code>/setup</code> — перенастроить LinkedIn"
        )
```

- [ ] **Step 2: Verify import**

Run: `python -c "from bot.handlers.start import router; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add bot/handlers/start.py
git commit -m "feat: /start status shows both destinations + new commands"
```

---

### Task 13: README update

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add Instagram + toggle docs**

In the commands table of `README.md`, add these rows after the `/approve` row:

```markdown
| `/iglogin <user> <pass> [totp]` | Подключить Instagram (сообщение удалится) |
| `/iglogout` | Отключить Instagram |
| `/linkedin on\|off` | Пауза публикации в LinkedIn |
| `/instagram on\|off` | Пауза публикации в Instagram |
| `/destinations` | Статус: куда публикуем |
```

Add a new section after the "Режим подтверждения постов" section:

```markdown
## Instagram (опционально)

Подключение личного аккаунта через `instagrapi` (неофициальный API).

```
/iglogin ваш_логин ваш_пароль
```

С 2FA через приложение (Authenticator) добавьте TOTP-секрет третьим аргументом
(base32-секрет из QR-кода):

```
/iglogin ваш_логин ваш_пароль TOTP_SECRET
```

При SMS/email-2FA бот попросит код в чате при входе.

> ⚠️ `instagrapi` использует приватный API Instagram — есть небольшой риск бана
> при агрессивной отправке. Не публикуйте десятки постов в час.

## Пауза публикации (тумблеры)

Не отключая аккаунт, можно временно приостановить публикацию на платформу:

```
/linkedin off      # пауза LinkedIn
/instagram off     # пауза Instagram
/destinations      # посмотреть, куда сейчас публикуем
```
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: Instagram setup + destination toggles in README"
```

---

### Task 14: Final verification

- [ ] **Step 1: Compile-check every changed file**

Run:
```bash
python -m py_compile config.py models.py services/crypto.py services/instagram.py services/publisher.py services/storage.py bot/main.py bot/handlers/instagram.py bot/handlers/settings.py bot/handlers/channel.py bot/handlers/post.py bot/handlers/approval.py bot/handlers/start.py
```
Expected: no output (all compile).

- [ ] **Step 2: Import-check the whole app**

Run: `python -c "from bot.main import main; print('ALL OK')"`
Expected: `ALL OK`

- [ ] **Step 3: Commit any final tweaks if needed**

If Step 1 or 2 surfaced issues, fix them and commit:
```bash
git add -A && git commit -m "fix: resolve final import/compile issues"
```

---

## Self-Review Checklist

- [x] **Spec coverage:**
  - `/iglogin` (creds + message delete + encrypt) → Task 6
  - `/iglogout` → Task 6
  - TOTP 2FA → Task 4 (pyotp in `login`) + Task 6 (3rd arg)
  - SMS/email 2FA → Task 4 (challenge handler + future bridge) + Task 6 (ask_code + FSM)
  - Per-destination toggles `/linkedin|instagram on|off` → Task 7
  - `/destinations` → Task 7
  - Publisher routes to connected+enabled → Task 5 + Tasks 9–11
  - Instagram single photo + carousel → Task 4 (`photo_upload`/`album_upload`)
  - Encryption (Fernet, ENCRYPTION_KEY) → Tasks 1–2
  - Missing ENCRYPTION_KEY refuses to start → pydantic `encryption_key: str` (Task 1) raises at `get_settings()`
- [x] **Placeholder scan:** no TBD/TODO/vague steps; every code step shows full code.
- [x] **Type consistency:** `Publisher.publish_to_all(user, text, photo_file_ids)` matches across Tasks 5, 9, 10, 11. `InstagramClient.publish(user_id, username, password_enc, totp_secret_enc, caption, image_paths)` matches Task 4 def and Task 5 call. `DestResult` fields (`name`, `ok`, `detail`, `icon`) consistent. Storage method names (`set_instagram_creds`, `clear_instagram_creds`, `set_linkedin_enabled`, `set_instagram_enabled`, `get_all_active_users`) match between Task 3 defs and Tasks 6/9 calls.
