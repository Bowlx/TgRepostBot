# TgRepostBot — Design Spec

## Overview

Telegram bot that forwards posts (text + images) to LinkedIn with automatic translation.
Built with Python + aiogram 3.x, deployed via Docker on VPS.

## Requirements

### Functional

1. **Receive Telegram posts** — two modes:
   - **Auto-mode**: Bot is added as a subscriber to a Telegram channel and receives `channel_post` events automatically
   - **Manual mode**: User forwards a post to the bot in private chat or uses a command
2. **Translate text** — user-configurable language pair via `/setlang source target` (e.g. `ru en`)
3. **Post to LinkedIn** — publish translated text + images via LinkedIn UGC API with OAuth 2.0
4. **Preview before posting** — user can preview translated text before publishing

### Non-Functional

- Async architecture (Python asyncio)
- SQLite for user settings persistence
- Docker deployment with docker-compose
- Configuration via environment variables and `.env` file

## Architecture

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  Telegram     │────▶│  TgRepostBot │────▶│  LinkedIn    │
│  (aiogram 3) │     │  (Python)    │     │  UGC API     │
└──────────────┘     │              │     └──────────────┘
                     │  ┌────────┐  │     ┌──────────────┐
                     │  │Google  │  │────▶│ Google Cloud │
                     │  │Translate│ │     │ Translation  │
                     │  └────────┘  │     └──────────────┘
                     │              │
                     │  ┌────────┐  │
                     │  │SQLite  │  │
                     │  │(state) │  │
                     │  └────────┘  │
                     └──────────────┘
```

## Project Structure

```
TgRepostBot/
├── bot/
│   ├── __init__.py
│   ├── main.py              # Entry point — bot startup
│   ├── handlers/
│   │   ├── __init__.py
│   │   ├── start.py         # /start command
│   │   ├── settings.py      # /setlang, /auth commands
│   │   ├── channel.py       # channel_post handler (auto-mode)
│   │   ├── forward.py       # forwarded message handler (manual mode)
│   │   └── post.py          # /post, /preview commands
│   └── keyboards.py         # Inline keyboards for UI
├── services/
│   ├── __init__.py
│   ├── linkedin.py          # LinkedIn UGC API client
│   ├── translator.py        # Google Cloud Translation client
│   └── storage.py           # SQLite storage (aiosqlite)
├── config.py                # Env-based configuration
├── models.py                # Data models (Pydantic)
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .env.example
└── README.md                # Setup guide + VPS deployment instructions
```

## Module Details

### config.py

Loads all configuration from environment variables:

| Variable | Required | Description |
|----------|----------|-------------|
| `BOT_TOKEN` | Yes | Telegram Bot API token (from @BotFather) |
| `LINKEDIN_CLIENT_ID` | Yes | LinkedIn App Client ID |
| `LINKEDIN_CLIENT_SECRET` | Yes | LinkedIn App Client Secret |
| `LINKEDIN_REDIRECT_URI` | Yes | OAuth redirect URI |
| `GOOGLE_TRANSLATE_API_KEY` | Yes | Google Cloud Translation API key |
| `DATABASE_PATH` | No | SQLite DB path (default: `data/bot.db`) |
| `DEFAULT_SOURCE_LANG` | No | Default source language (default: `ru`) |
| `DEFAULT_TARGET_LANG` | No | Default target language (default: `en`) |

### services/storage.py

SQLite async storage using aiosqlite. Tables:

- **users** — `user_id`, `source_lang`, `target_lang`, `linkedin_access_token`, `linkedin_person_urn`, `created_at`
- **pending_posts** — `user_id`, `original_text`, `translated_text`, `photo_file_ids` (JSON array), `created_at`

Key methods:
- `get_user(user_id)` / `save_user(user_id, data)`
- `update_languages(user_id, source, target)`
- `update_linkedin_token(user_id, access_token, person_urn)`
- `save_pending_post(user_id, text, translated, photos)` / `get_pending_post(user_id)`

### services/translator.py

Google Cloud Translation API v2 (REST) wrapper:

- `translate(text, source_lang, target_lang) -> str`
- Uses API key authentication (no service account needed)
- Handles rate limiting with retries (aiohttp retry)

### services/linkedin.py

LinkedIn API client with three-step image upload:

1. **OAuth flow**:
   - Generate auth URL → user opens in browser → callback with code
   - Exchange code for access_token + fetch person URN
2. **Image upload** (per image):
   - `POST /v2/assets?action=registerUpload` — get upload URL + asset URN
   - `PUT <uploadUrl>` — upload binary image data
3. **Post creation**:
   - `POST /v2/ugcPosts` — create post with translated text + media assets
   - Text-only post if no images
   - Visibility: `PUBLIC`

### bot/handlers/

**start.py**: `/start` — register user, show welcome message with instructions

**settings.py**:
- `/setlang <source> <target>` — update language pair
- `/auth` — initiate LinkedIn OAuth (generates URL, user clicks, provides code)
- `/callback <code>` — complete OAuth flow

**channel.py**: `channel_post` handler — auto-process new channel posts:
1. Extract text and photo file_ids
2. Download photos via Bot API
3. Translate text
4. Post to LinkedIn immediately (if user has valid LinkedIn token)

**forward.py**: Handles forwarded messages in private chat:
1. Store original text + photos as pending post
2. Translate text
3. Show preview

**post.py**:
- `/preview` — show translated text of pending post
- `/post` — publish pending post to LinkedIn
- `/skip` — cancel pending post

## Data Flow

### Auto-mode (Channel Post)

```
Channel Post → channel_post handler
  → extract text + photos
  → translator.translate(text, source, target)
  → linkedin.upload_images(photos)  [if photos present]
  → linkedin.create_post(text, image_urns)
  → reply with success/failure
```

### Manual-mode (Forwarded Message)

```
Forwarded Message → forward handler
  → store as pending_post
  → translator.translate(text, source, target)
  → reply with preview + "Use /post to publish or /skip to cancel"
/post → linkedin.upload_images + create_post
  → reply with success/failure
```

## Error Handling

- LinkedIn API errors → show user-friendly message + suggest re-auth
- Translation API errors → post without translation, notify user
- Missing LinkedIn token → prompt to run `/auth`
- Image download failure → post text only, notify about failed images

## Docker Deployment

### Dockerfile

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "-m", "bot.main"]
```

### docker-compose.yml

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

## Dependencies (requirements.txt)

```
aiogram==3.*
aiohttp
aiosqlite
google-cloud-translate
python-dotenv
pydantic
```

## LinkedIn App Setup Requirements

User must create a LinkedIn App at https://www.linkedin.com/developers/ with:
- "Share on LinkedIn" product enabled
- OAuth 2.0 redirect URI configured
- Client ID and Client Secret obtained

## VPS Deployment Steps (for README.md)

1. Clone repo
2. Copy `.env.example` to `.env`, fill in all secrets
3. `docker compose up -d`
4. Open bot in Telegram, run `/start`
5. Run `/auth` to connect LinkedIn
6. Add bot to Telegram channel (for auto-mode)
7. Or forward posts directly to bot (for manual-mode)
