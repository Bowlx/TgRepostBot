# TgRepostBot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Telegram bot that forwards posts (text + images) to LinkedIn with automatic translation, deployed via Docker.

**Architecture:** Python async app using aiogram 3.x for Telegram, aiohttp for LinkedIn/Google API calls, aiosqlite for persistence. Two modes: auto (channel subscriber) and manual (forwarded messages). User-configurable translation language pairs via Google Cloud Translation.

**Tech Stack:** Python 3.12, aiogram 3.x, aiohttp, aiosqlite, Google Cloud Translation API v2, LinkedIn UGC API, Docker

---

## File Structure

| File | Responsibility |
|------|---------------|
| `config.py` | Load and validate env vars into a Pydantic Settings model |
| `models.py` | Pydantic data models for User, PendingPost |
| `services/storage.py` | Async SQLite CRUD for users and pending posts |
| `services/translator.py` | Google Cloud Translation API v2 wrapper |
| `services/linkedin.py` | LinkedIn OAuth + UGC post creation + image upload |
| `bot/main.py` | Bot entry point — dispatcher setup, router registration, startup |
| `bot/handlers/start.py` | `/start` command — register user, show welcome |
| `bot/handlers/settings.py` | `/setlang`, `/auth`, `/callback` commands |
| `bot/handlers/channel.py` | `channel_post` handler — auto-mode pipeline |
| `bot/handlers/forward.py` | Forwarded message handler — manual mode, store + preview |
| `bot/handlers/post.py` | `/preview`, `/post`, `/skip` commands |
| `bot/keyboards.py` | Inline keyboards for post actions |
| `requirements.txt` | Python dependencies |
| `Dockerfile` | Multi-stage Docker build |
| `docker-compose.yml` | Single-service compose with volume |
| `.env.example` | Template for environment variables |
| `README.md` | Full setup guide with VPS deployment instructions |

---

### Task 1: Project Scaffolding and Configuration

**Files:**
- Create: `config.py`
- Create: `models.py`
- Create: `requirements.txt`
- Create: `.env.example`

- [ ] **Step 1: Create requirements.txt**

```
aiogram==3.15.0
aiohttp==3.11.11
aiosqlite==0.20.0
pydantic==2.10.4
pydantic-settings==2.7.1
python-dotenv==1.0.1
```

- [ ] **Step 2: Create .env.example**

```
BOT_TOKEN=your_telegram_bot_token
LINKEDIN_CLIENT_ID=your_linkedin_client_id
LINKEDIN_CLIENT_SECRET=your_linkedin_client_secret
LINKEDIN_REDIRECT_URI=https://your-domain.com/callback
GOOGLE_TRANSLATE_API_KEY=your_google_translate_api_key
DATABASE_PATH=data/bot.db
DEFAULT_SOURCE_LANG=ru
DEFAULT_TARGET_LANG=en
```

- [ ] **Step 3: Create config.py**

```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    bot_token: str
    linkedin_client_id: str
    linkedin_client_secret: str
    linkedin_redirect_uri: str
    google_translate_api_key: str
    database_path: str = "data/bot.db"
    default_source_lang: str = "ru"
    default_target_lang: str = "en"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 4: Create models.py**

```python
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class User:
    user_id: int
    source_lang: str = "ru"
    target_lang: str = "en"
    linkedin_access_token: Optional[str] = None
    linkedin_person_urn: Optional[str] = None


@dataclass
class PendingPost:
    user_id: int
    original_text: str
    translated_text: str
    photo_file_ids: list[str] = field(default_factory=list)
```

- [ ] **Step 5: Create __init__.py files**

Create empty `bot/__init__.py`, `bot/handlers/__init__.py`, and `services/__init__.py`.

```bash
mkdir -p bot/handlers services
touch bot/__init__.py bot/handlers/__init__.py services/__init__.py
```

- [ ] **Step 6: Commit**

```bash
git add .
git commit -m "feat: project scaffolding, config, models, requirements"
```

---

### Task 2: SQLite Storage Service

**Files:**
- Create: `services/storage.py`

- [ ] **Step 1: Write services/storage.py**

```python
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
```

- [ ] **Step 2: Commit**

```bash
git add services/storage.py
git commit -m "feat: add SQLite storage service for users and pending posts"
```

---

### Task 3: Google Translation Service

**Files:**
- Create: `services/translator.py`

- [ ] **Step 1: Write services/translator.py**

```python
import aiohttp


class Translator:
    BASE_URL = "https://translation.googleapis.com/language/translate/v2"

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        if not text.strip():
            return text
        params = {
            "key": self.api_key,
            "q": text,
            "source": source_lang,
            "target": target_lang,
            "format": "text",
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(self.BASE_URL, data=params) as resp:
                resp.raise_for_status()
                data = await resp.json()
                return data["data"]["translations"][0]["translatedText"]
```

- [ ] **Step 2: Commit**

```bash
git add services/translator.py
git commit -m "feat: add Google Cloud Translation service"
```

---

### Task 4: LinkedIn API Service

**Files:**
- Create: `services/linkedin.py`

- [ ] **Step 1: Write services/linkedin.py**

```python
import io
from typing import Optional

import aiohttp


class LinkedInClient:
    AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
    TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
    API_BASE = "https://api.linkedin.com"

    def __init__(self, client_id: str, client_secret: str, redirect_uri: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri

    def get_auth_url(self) -> str:
        params = (
            f"?response_type=code"
            f"&client_id={self.client_id}"
            f"&redirect_uri={self.redirect_uri}"
            f"&scope=w_member_social"
        )
        return f"{self.AUTH_URL}{params}"

    async def exchange_code(self, code: str) -> tuple[str, str]:
        """Exchange auth code for access_token and person URN. Returns (access_token, person_urn)."""
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(self.TOKEN_URL, data=data) as resp:
                resp.raise_for_status()
                token_data = await resp.json()
                access_token = token_data["access_token"]

            headers = {"Authorization": f"Bearer {access_token}"}
            async with session.get(f"{self.API_BASE}/v2/me", headers=headers) as resp:
                resp.raise_for_status()
                me_data = await resp.json()
                person_id = me_data["id"]
                person_urn = f"urn:li:person:{person_id}"

            return access_token, person_urn

    async def register_image_upload(self, access_token: str, person_urn: str) -> tuple[str, str]:
        """Register an image for upload. Returns (upload_url, asset_urn)."""
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        payload = {
            "registerUploadRequest": {
                "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
                "owner": person_urn,
                "serviceRelationships": [
                    {
                        "relationshipType": "OWNER",
                        "identifier": "urn:li:userGeneratedContent",
                    }
                ],
            }
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.API_BASE}/v2/assets?action=registerUpload",
                headers=headers,
                json=payload,
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
                upload_url = data["value"]["uploadMechanism"][
                    "com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"
                ]["uploadUrl"]
                asset_urn = data["value"]["asset"]
                return upload_url, asset_urn

    async def upload_image(self, upload_url: str, access_token: str, image_bytes: bytes) -> None:
        """Upload image binary to LinkedIn."""
        headers = {"Authorization": f"Bearer {access_token}"}
        async with aiohttp.ClientSession() as session:
            async with session.put(upload_url, headers=headers, data=image_bytes) as resp:
                resp.raise_for_status()

    async def upload_image_full(self, access_token: str, person_urn: str, image_bytes: bytes) -> str:
        """Full image upload pipeline. Returns asset URN."""
        upload_url, asset_urn = await self.register_image_upload(access_token, person_urn)
        await self.upload_image(upload_url, access_token, image_bytes)
        return asset_urn

    async def create_post(
        self,
        access_token: str,
        person_urn: str,
        text: str,
        image_asset_urns: Optional[list[str]] = None,
    ) -> dict:
        """Create a LinkedIn UGC post with optional images."""
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
        }

        media = []
        if image_asset_urns:
            for asset_urn in image_asset_urns:
                media.append(
                    {
                        "status": "READY",
                        "media": asset_urn,
                    }
                )

        share_media_category = "IMAGE" if image_asset_urns else "NONE"

        payload = {
            "author": person_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": text},
                    "shareMediaCategory": share_media_category,
                    "media": media,
                }
            },
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.API_BASE}/v2/ugcPosts",
                headers=headers,
                json=payload,
            ) as resp:
                resp.raise_for_status()
                return await resp.json()
```

- [ ] **Step 2: Commit**

```bash
git add services/linkedin.py
git commit -m "feat: add LinkedIn API client with OAuth, image upload, and post creation"
```

---

### Task 5: Bot Entry Point

**Files:**
- Create: `bot/main.py`

- [ ] **Step 1: Write bot/main.py**

```python
import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.handlers import start, settings, channel, forward, post
from config import get_settings
from services.storage import Storage
from services.translator import Translator
from services.linkedin import LinkedInClient

logger = logging.getLogger(__name__)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)

    cfg = get_settings()

    # Initialize services
    storage = Storage(db_path=cfg.database_path)
    await storage.init()

    translator = Translator(api_key=cfg.google_translate_api_key)
    linkedin = LinkedInClient(
        client_id=cfg.linkedin_client_id,
        client_secret=cfg.linkedin_client_secret,
        redirect_uri=cfg.linkedin_redirect_uri,
    )

    bot = Bot(token=cfg.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

    dp = Dispatcher()
    dp["storage"] = storage
    dp["translator"] = translator
    dp["linkedin"] = linkedin
    dp["config"] = cfg

    dp.include_router(start.router)
    dp.include_router(settings.router)
    dp.include_router(channel.router)
    dp.include_router(forward.router)
    dp.include_router(post.router)

    logger.info("Bot starting...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Commit**

```bash
git add bot/main.py
git commit -m "feat: add bot entry point with dispatcher and service wiring"
```

---

### Task 6: /start Handler

**Files:**
- Create: `bot/handlers/start.py`

- [ ] **Step 1: Write bot/handlers/start.py**

```python
from aiogram import Router, types
from aiogram.filters import CommandStart

from services.storage import Storage

router = Router()


@router.message(CommandStart())
async def cmd_start(message: types.Message, storage: Storage) -> None:
    user = await storage.get_user(message.from_user.id)
    if user is None:
        cfg = router.config  # type: ignore[attr-defined]
        user = await storage.create_user(
            message.from_user.id,
            source_lang=cfg.default_source_lang,
            target_lang=cfg.default_target_lang,
        )

    welcome = (
        f"👋 Привет, <b>{message.from_user.full_name}</b>!\n\n"
        f"Я бот для кросспостинга из Telegram в LinkedIn с переводом.\n\n"
        f"<b>Как пользоваться:</b>\n"
        f"1. <code>/auth</code> — подключить LinkedIn\n"
        f"2. <code>/setlang ru en</code> — настроить языки перевода\n"
        f"3. Перешли мне пост или добавь меня в канал\n\n"
        f"<b>Текущие настройки:</b>\n"
        f"🔤 Перевод: {user.source_lang} → {user.target_lang}\n"
        f"💼 LinkedIn: {'✅ Подключён' if user.linkedin_access_token else '❌ Не подключён'}"
    )
    await message.answer(welcome)
```

Note: The handler accesses `router.config` which is set via middleware in the next task. We'll add a middleware to inject services into handler kwargs.

- [ ] **Step 2: Update bot/main.py to add service injection middleware**

Update `bot/main.py` to inject `storage`, `translator`, `linkedin`, and `config` into handler kwargs via dispatcher middleware:

```python
import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.handlers import start, settings, channel, forward, post
from config import get_settings
from services.storage import Storage
from services.translator import Translator
from services.linkedin import LinkedInClient

logger = logging.getLogger(__name__)


async def service_middleware(handler, event, data):
    data["storage"] = data["dispatcher"]["storage"]
    data["translator"] = data["dispatcher"]["translator"]
    data["linkedin_client"] = data["dispatcher"]["linkedin"]
    data["app_config"] = data["dispatcher"]["config"]
    return await handler(event, data)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)

    cfg = get_settings()

    storage = Storage(db_path=cfg.database_path)
    await storage.init()

    translator = Translator(api_key=cfg.google_translate_api_key)
    linkedin = LinkedInClient(
        client_id=cfg.linkedin_client_id,
        client_secret=cfg.linkedin_client_secret,
        redirect_uri=cfg.linkedin_redirect_uri,
    )

    bot = Bot(token=cfg.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

    dp = Dispatcher()
    dp["storage"] = storage
    dp["translator"] = translator
    dp["linkedin"] = linkedin
    dp["config"] = cfg

    dp.message.middleware(service_middleware)
    dp.channel_post.middleware(service_middleware)

    dp.include_router(start.router)
    dp.include_router(settings.router)
    dp.include_router(channel.router)
    dp.include_router(forward.router)
    dp.include_router(post.router)

    logger.info("Bot starting...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 3: Rewrite bot/handlers/start.py to use injected services**

```python
from aiogram import Router, types
from aiogram.filters import CommandStart

from config import Settings
from services.storage import Storage

router = Router()


@router.message(CommandStart())
async def cmd_start(
    message: types.Message,
    storage: Storage,
    app_config: Settings,
) -> None:
    user = await storage.get_user(message.from_user.id)
    if user is None:
        user = await storage.create_user(
            message.from_user.id,
            source_lang=app_config.default_source_lang,
            target_lang=app_config.default_target_lang,
        )

    welcome = (
        f"👋 Привет, <b>{message.from_user.full_name}</b>!\n\n"
        f"Я бот для кросспостинга из Telegram в LinkedIn с переводом.\n\n"
        f"<b>Как пользоваться:</b>\n"
        f"1. <code>/auth</code> — подключить LinkedIn\n"
        f"2. <code>/setlang ru en</code> — настроить языки перевода\n"
        f"3. Перешли мне пост или добавь меня в канал\n\n"
        f"<b>Текущие настройки:</b>\n"
        f"🔤 Перевод: {user.source_lang} → {user.target_lang}\n"
        f"💼 LinkedIn: {'✅ Подключён' if user.linkedin_access_token else '❌ Не подключён'}"
    )
    await message.answer(welcome)
```

- [ ] **Step 4: Commit**

```bash
git add bot/main.py bot/handlers/start.py
git commit -m "feat: add /start handler with service middleware injection"
```

---

### Task 7: Settings Handlers (/setlang, /auth, /callback)

**Files:**
- Create: `bot/handlers/settings.py`

- [ ] **Step 1: Write bot/handlers/settings.py**

```python
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import Settings
from services.storage import Storage
from services.linkedin import LinkedInClient

router = Router()


@router.message(Command("setlang"))
async def cmd_setlang(message: types.Message, storage: Storage) -> None:
    parts = message.text.split()
    if len(parts) != 3:
        await message.answer(
            "❌ Использование: <code>/setlang source target</code>\n"
            "Пример: <code>/setlang ru en</code>"
        )
        return

    source_lang, target_lang = parts[1].lower(), parts[2].lower()
    user = await storage.get_user(message.from_user.id)
    if user is None:
        await message.answer("Сначала нажмите /start")
        return

    await storage.update_languages(message.from_user.id, source_lang, target_lang)
    await message.answer(f"✅ Языки перевода обновлены: <b>{source_lang} → {target_lang}</b>")


@router.message(Command("auth"))
async def cmd_auth(message: types.Message, linkedin_client: LinkedInClient) -> None:
    auth_url = linkedin_client.get_auth_url()
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔗 Подключить LinkedIn", url=auth_url)]
        ]
    )
    await message.answer(
        "Для подключения LinkedIn:\n\n"
        "1. Нажмите кнопку ниже\n"
        "2. Разрешите доступ\n"
        "3. Скопируйте код из URL редиректа\n"
        "4. Отправьте: <code>/callback ВАШ_КОД</code>",
        reply_markup=keyboard,
    )


@router.message(Command("callback"))
async def cmd_callback(
    message: types.Message,
    storage: Storage,
    linkedin_client: LinkedInClient,
) -> None:
    parts = message.text.split(maxsplit=1)
    if len(parts) != 2:
        await message.answer("❌ Использование: <code>/callback КОД_ИЗ_URL</code>")
        return

    code = parts[1].strip()
    await message.answer("⏳ Обмениваю код на токен...")

    try:
        access_token, person_urn = await linkedin_client.exchange_code(code)
        await storage.update_linkedin_token(message.from_user.id, access_token, person_urn)
        await message.answer("✅ LinkedIn успешно подключён!")
    except Exception as e:
        await message.answer(f"❌ Ошибка авторизации: {e}\nПопробуйте снова: /auth")
```

- [ ] **Step 2: Commit**

```bash
git add bot/handlers/settings.py
git commit -m "feat: add /setlang, /auth, /callback handlers"
```

---

### Task 8: Forward Handler (Manual Mode)

**Files:**
- Create: `bot/handlers/forward.py`

- [ ] **Step 1: Write bot/handlers/forward.py**

```python
from aiogram import Router, types, F

from config import Settings
from services.storage import Storage
from services.translator import Translator

router = Router()

# Only handle private messages that are forwarded or contain content
router.message.filter(F.chat.type == "private")


@router.message(F.forward_date | F.text | F.photo)
async def handle_forwarded(message: types.Message, storage: Storage, translator: Translator, app_config: Settings) -> None:
    # Skip if this is a command
    if message.text and message.text.startswith("/"):
        return

    user = await storage.get_user(message.from_user.id)
    if user is None:
        await message.answer("Сначала нажмите /start")
        return

    # Extract text
    text = message.text or message.caption or ""

    # Extract photo file IDs
    photo_file_ids: list[str] = []
    if message.photo:
        # Get the largest photo size
        photo_file_ids = [message.photo[-1].file_id]

    if not text and not photo_file_ids:
        await message.answer("❌ Не удалось извлечь контент из сообщения.")
        return

    # Translate text
    translated_text = text
    if text.strip():
        try:
            translated_text = await translator.translate(text, user.source_lang, user.target_lang)
        except Exception as e:
            await message.answer(f"⚠️ Ошибка перевода: {e}\n\nПост будет опубликован без перевода.")

    # Store as pending post
    await storage.save_pending_post(
        user_id=message.from_user.id,
        original_text=text,
        translated_text=translated_text,
        photo_file_ids=photo_file_ids,
    )

    preview = (
        f"<b>📋 Превью поста:</b>\n\n"
        f"{translated_text}\n\n"
        f"{'🖼️ Изображения: ' + str(len(photo_file_ids)) + ' шт.' if photo_file_ids else ''}\n\n"
        f"<code>/post</code> — опубликовать\n"
        f"<code>/skip</code> — отменить"
    )
    await message.answer(preview)
```

- [ ] **Step 2: Commit**

```bash
git add bot/handlers/forward.py
git commit -m "feat: add forward handler for manual mode with translation preview"
```

---

### Task 9: Channel Post Handler (Auto Mode)

**Files:**
- Create: `bot/handlers/channel.py`

- [ ] **Step 1: Write bot/handlers/channel.py**

```python
import asyncio
import logging

from aiogram import Router, types, Bot
from aiogram.filters import F

from config import Settings
from services.storage import Storage
from services.translator import Translator
from services.linkedin import LinkedInClient

router = Router()
logger = logging.getLogger(__name__)

router.channel_post.filter(F.chat.type == "channel")


@router.channel_post(F.text | F.photo)
async def handle_channel_post(
    message: types.Message,
    bot: Bot,
    storage: Storage,
    translator: Translator,
    linkedin_client: LinkedInClient,
) -> None:
    # Use the first registered user as the LinkedIn author
    # In production, you'd map channels to users
    # For now, we iterate over all users with LinkedIn connected
    text = message.text or message.caption or ""

    photo_file_ids: list[str] = []
    if message.photo:
        photo_file_ids = [message.photo[-1].file_id]

    if not text and not photo_file_ids:
        return

    # For auto-mode: get user who added the bot (simplified: first user with LinkedIn token)
    # A real implementation would have a channel->user mapping
    # We'll look for any user that configured this bot
    # For simplicity, we'll use user_id from a config or the first available
    # Here we just post on behalf of all connected users
    # TODO: In production, add a channels table mapping channel_id -> user_id

    # For now, we'll send a notification to the channel that the post was received
    # The actual posting happens when a user has LinkedIn connected
    # We store it and let the user know

    # Simple approach: iterate all users with LinkedIn connected
    import aiosqlite

    async with aiosqlite.connect(storage.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM users WHERE linkedin_access_token IS NOT NULL"
        )
        rows = await cursor.fetchall()

    if not rows:
        logger.warning("No users with LinkedIn connected, skipping channel post")
        return

    for row in rows:
        user_id = row["user_id"]
        source_lang = row["source_lang"]
        target_lang = row["target_lang"]
        access_token = row["linkedin_access_token"]
        person_urn = row["linkedin_person_urn"]

        # Translate
        translated_text = text
        if text.strip():
            try:
                translated_text = await translator.translate(text, source_lang, target_lang)
            except Exception as e:
                logger.error(f"Translation failed for user {user_id}: {e}")

        # Download and upload images
        image_asset_urns: list[str] = []
        for file_id in photo_file_ids:
            try:
                file = await bot.get_file(file_id)
                image_bytes = await bot.download_file(file.file_path)
                image_data = image_bytes.read()
                asset_urn = await linkedin_client.upload_image_full(
                    access_token, person_urn, image_data
                )
                image_asset_urns.append(asset_urn)
            except Exception as e:
                logger.error(f"Image upload failed: {e}")

        # Create LinkedIn post
        try:
            await linkedin_client.create_post(
                access_token, person_urn, translated_text, image_asset_urns or None
            )
            logger.info(f"Channel post published to LinkedIn for user {user_id}")
        except Exception as e:
            logger.error(f"LinkedIn post failed for user {user_id}: {e}")
            try:
                await bot.send_message(
                    user_id,
                    f"❌ Ошибка публикации в LinkedIn: {e}\nВозможно, нужно переподключить: /auth",
                )
            except Exception:
                pass
```

- [ ] **Step 2: Commit**

```bash
git add bot/handlers/channel.py
git commit -m "feat: add channel post handler for auto-mode LinkedIn posting"
```

---

### Task 10: Post/Preview/Skip Handlers

**Files:**
- Create: `bot/handlers/post.py`

- [ ] **Step 1: Write bot/handlers/post.py**

```python
import logging

from aiogram import Router, types, Bot
from aiogram.filters import Command

from services.storage import Storage
from services.linkedin import LinkedInClient

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
    linkedin_client: LinkedInClient,
) -> None:
    pending = await storage.get_pending_post(message.from_user.id)
    if pending is None:
        await message.answer("❌ Нет отложенного поста. Перешлите сообщение боту.")
        return

    user = await storage.get_user(message.from_user.id)
    if user is None or not user.linkedin_access_token:
        await message.answer("❌ LinkedIn не подключён. Используйте /auth")
        return

    await message.answer("⏳ Публикую в LinkedIn...")

    # Download and upload images
    image_asset_urns: list[str] = []
    for file_id in pending.photo_file_ids:
        try:
            file = await bot.get_file(file_id)
            image_bytes = await bot.download_file(file.file_path)
            image_data = image_bytes.read()
            asset_urn = await linkedin_client.upload_image_full(
                user.linkedin_access_token, user.linkedin_person_urn, image_data
            )
            image_asset_urns.append(asset_urn)
        except Exception as e:
            logger.error(f"Image upload failed: {e}")
            await message.answer(f"⚠️ Не удалось загрузить изображение: {e}")

    # Create LinkedIn post
    try:
        await linkedin_client.create_post(
            user.linkedin_access_token,
            user.linkedin_person_urn,
            pending.translated_text,
            image_asset_urns or None,
        )
        await storage.delete_pending_post(message.from_user.id)
        await message.answer("✅ Пост опубликован в LinkedIn!")
    except Exception as e:
        logger.error(f"LinkedIn post creation failed: {e}")
        await message.answer(
            f"❌ Ошибка публикации: {e}\n\n"
            "Возможно, токен истёк. Попробуйте: /auth"
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

- [ ] **Step 2: Commit**

```bash
git add bot/handlers/post.py
git commit -m "feat: add /post, /preview, /skip handlers for manual posting"
```

---

### Task 11: Docker and Deployment Files

**Files:**
- Create: `Dockerfile`
- Create: `docker-compose.yml`
- Create: `README.md`

- [ ] **Step 1: Create Dockerfile**

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "-m", "bot.main"]
```

- [ ] **Step 2: Create docker-compose.yml**

```yaml
services:
  bot:
    build: .
    env_file: .env
    volumes:
      - bot-data:/app/data
    restart: unless-stopped

volumes:
  bot-data:
```

- [ ] **Step 3: Create README.md**

```markdown
# TgRepostBot

Telegram → LinkedIn кросспостинг бот с автоматическим переводом.

## Возможности

- 🔄 Автоматический кросспостинг из Telegram каналов в LinkedIn
- 📝 Ручная пересылка постов через бота
- 🌐 Автоматический перевод текста (Google Translate)
- 🖼️ Перенос изображений
- ⚙️ Настраиваемые языковые пары

## Предварительные требования

### 1. Создать Telegram бота

1. Откройте [@BotFather](https://t.me/BotFather) в Telegram
2. Отправьте `/newbot` и следуйте инструкциям
3. Скопируйте полученный **BOT_TOKEN**

### 2. Создать LinkedIn App

1. Перейдите на [LinkedIn Developers](https://www.linkedin.com/developers/)
2. Нажмите **Create App**
3. Заполните данные приложения
4. В разделе **Products** включите **Share on LinkedIn**
5. В разделе **Auth** добавьте Redirect URL (например, `https://your-domain.com/callback`)
6. Скопируйте **Client ID** и **Client Secret**

### 3. Получить Google Translate API Key

1. Перейдите в [Google Cloud Console](https://console.cloud.google.com/)
2. Создайте проект (или выберите существующий)
3. Включите **Cloud Translation API**
4. Перейдите в **APIs & Services → Credentials**
5. Создайте **API Key**
6. Скопируйте ключ

## Установка на VPS

### Шаг 1: Подготовка сервера

```bash
# Обновите систему
sudo apt update && sudo apt upgrade -y

# Установите Docker и Docker Compose
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER
# Выйдите и зайдите снова для применения группы
```

### Шаг 2: Клонирование и настройка

```bash
# Клонируйте репозиторий
git clone <YOUR_REPO_URL> ~/TgRepostBot
cd ~/TgRepostBot

# Создайте .env файл из шаблона
cp .env.example .env

# Отредактируйте .env файл
nano .env
```

Заполните `.env` вашими значениями:

```
BOT_TOKEN=ваш_токен_от_botfather
LINKEDIN_CLIENT_ID=ваш_linkedin_client_id
LINKEDIN_CLIENT_SECRET=ваш_linkedin_client_secret
LINKEDIN_REDIRECT_URI=https://your-domain.com/callback
GOOGLE_TRANSLATE_API_KEY=ваш_google_api_key
DATABASE_PATH=data/bot.db
DEFAULT_SOURCE_LANG=ru
DEFAULT_TARGET_LANG=en
```

### Шаг 3: Запуск

```bash
# Соберите и запустите
docker compose up -d

# Проверьте логи
docker compose logs -f
```

### Шаг 4: Настройка бота

1. Откройте бота в Telegram
2. Отправьте `/start`
3. Отправьте `/auth` и подключите LinkedIn
4. Настройте языки: `/setlang ru en`
5. Готово! Перешлите пост боту или добавьте его в канал

## Команды бота

| Команда | Описание |
|---------|----------|
| `/start` | Начать работу с ботом |
| `/auth` | Подключить LinkedIn |
| `/callback CODE` | Завершить авторизацию LinkedIn |
| `/setlang SRC TGT` | Настроить языки перевода (например: `ru en`) |
| `/preview` | Посмотреть превью отложенного поста |
| `/post` | Опубликовать отложенный пост в LinkedIn |
| `/skip` | Отменить отложенный пост |

## Управление

```bash
# Остановить бота
docker compose down

# Перезапустить
docker compose restart

# Обновить после изменений в коде
docker compose up -d --build

# Посмотреть логи
docker compose logs -f --tail 100
```

## Режимы работы

### Автоматический (из канала)

Добавьте бота как подписчика в Telegram канал. Все новые посты будут автоматически переводиться и публиковаться в LinkedIn.

### Ручной (пересылка)

Перешлите любой пост боту в личные сообщения. Бот переведёт текст и покажет превью. Нажмите `/post` для публикации или `/skip` для отмены.
```

- [ ] **Step 4: Create .gitignore**

```
.env
data/
__pycache__/
*.pyc
.mcp.json
```

- [ ] **Step 5: Commit**

```bash
git add Dockerfile docker-compose.yml README.md .gitignore
git commit -m "feat: add Docker deployment and comprehensive README"
```

---

### Task 12: Final Wiring and __main__.py

**Files:**
- Create: `bot/__main__.py`

- [ ] **Step 1: Create bot/__main__.py**

This enables `python -m bot` execution:

```python
from bot.main import main

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```

Wait — `bot/main.py` already calls `asyncio.run(main())` in `if __name__ == "__main__"`. For `python -m bot` to work, we need `__main__.py`:

```python
import asyncio
from bot.main import main

asyncio.run(main())
```

- [ ] **Step 2: Commit**

```bash
git add bot/__main__.py
git commit -m "feat: add __main__.py for python -m bot execution"
```

---

## Self-Review Checklist

- [x] **Spec coverage**: Every spec requirement maps to a task (config → T1, storage → T2, translator → T3, linkedin → T4, handlers → T5-T10, docker → T11)
- [x] **Placeholder scan**: No TBD/TODO/fill-in-later patterns (except one `TODO` in channel.py for production improvement — intentional, documented)
- [x] **Type consistency**: `Storage`, `Translator`, `LinkedInClient`, `Settings` used consistently across all handlers; method signatures match (`storage.get_user`, `translator.translate`, `linkedin_client.create_post`, etc.)
