# Instagram Destination + Destination Toggles — Design Spec

## Overview

Add Instagram as a second publishing destination (via the `instagrapi` private-API
library) alongside LinkedIn, and add per-destination enable/disable toggles so a
user can temporarily pause posting to one platform without disconnecting it.

## Background / Constraints

- The bot is effectively single-user (Diana). All Telegram posts have images.
- LinkedIn uses OAuth (token stored). Instagram via `instagrapi` uses
  username + password (session-based, password must be stored for re-login).
- Instagram has no text-only feed posts, but **all posts here have images**,
  so this constraint is irrelevant.
- `instagrapi` is synchronous (`requests`-based); all calls run in
  `asyncio.to_thread` to avoid blocking the event loop.
- Instagram credentials are sensitive: the password is sent via chat but
  (a) the chat message is deleted immediately after reading, and (b) the
  password is stored **encrypted** in the DB.

## Requirements

### Functional

1. **Connect Instagram** via `/iglogin <username> <password> [totp_secret]`:
   - Logs in through `instagrapi`, saves a session file.
   - Deletes the user's message containing the password immediately.
   - Stores username (plaintext), password (Fernet-encrypted), and the
     optional TOTP secret (Fernet-encrypted) in DB.
   - Instagram is **enabled by default** after a successful login.
   - **2FA support** (both kinds — see "2FA Handling" below):
     - TOTP (authenticator app): fully automatic via `pyotp`.
     - SMS/email challenge: interactive — bot prompts the user for the code
       and resolves the challenge.
2. **Disconnect Instagram** via `/iglogout` — removes credentials + session file.
3. **Per-destination toggles**:
   - `/linkedin on|off` and `/instagram on|off` toggle publishing without
     disconnecting (credentials are preserved).
   - `/destinations` shows status: connected + enabled per platform.
4. **Publishing**: a post goes to every destination that is both *connected*
   and *enabled* for that user. The result message reports per-destination
   outcome (✅/❌/⏸ off).
5. Instagram posting supports **single photo** and **multi-photo carousel**
   (album) via `instagrapi`'s `photo_upload` / `album_upload`.

### Non-Functional

- Encryption uses `cryptography.fernet.Fernet`; key read from `ENCRYPTION_KEY`
  in `.env` (sits next to `BOT_TOKEN`, equally sensitive).
- All Instagram calls are off-thread (`asyncio.to_thread`).
- No LinkedIn behavior changes except routing through the new publisher layer.

## Architecture

```
Post ready to publish (channel / /post / approval-publish)
        │
        ▼
services/publisher.py  →  publish_to_all(user, text, photo_paths)
        │
        ├─ LinkedIn: token present & linkedin_enabled  → linkedin.publish(...)
        ├─ Instagram: session present & instagram_enabled → instagram.publish(...)
        └─ collects per-destination results, returns list[DestResult]
```

Each destination is a small strategy object with a uniform interface so
`channel.py`, `post.py`, and `approval.py` stop hard-coding LinkedIn and just
call the publisher.

## 2FA Handling

Instagram accounts may require 2FA at login. Both common forms are supported:

**TOTP (authenticator app — Google Authenticator / Authy):**
- The user passes the TOTP secret (the base32 seed from the QR code) as the
  optional third `/iglogin` argument.
- Stored Fernet-encrypted in DB (`instagram_totp_secret_enc`).
- At every login, `pyotp.TOTP(secret).now()` generates the 6-digit code and
  is passed as `verification_code` to `instagrapi`'s `login()`. Fully
  automatic — no user interaction after setup.

**SMS / email challenge:**
- When `cl.login()` raises `ChallengeRequired`, the login coroutine (running
  in a worker thread) signals the async side. The bot asks the user for the
  code ("Введите код из SMS/email"), FSM waits up to ~5 min for the reply,
  and the code is fed to `instagrapi`'s challenge resolver.
- Implemented via an `asyncio` event/future bridge between the login thread
  and the FSM handler; the user code is forwarded back into the thread.

If no 2FA is configured on the account, neither path activates and login
proceeds normally with just username + password.

## Components

### services/crypto.py (new)

```python
class Crypto:
    def __init__(self, key: str): ...        # Fernet(key)
    def encrypt(self, plaintext: str) -> str  # returns base64 token
    def decrypt(self, token: str) -> str
```

Key comes from `ENCRYPTION_KEY` (`.env`). Only the Instagram password is
encrypted; the LinkedIn OAuth token and Instagram username are stored as-is.

### services/instagram.py (new)

```python
class InstagramClient:
    def __init__(self, session_dir: str, crypto: Crypto,
                 code_provider=None): ...
        # code_provider: async callable(user_id, choice) -> str, used to ask
        # the user for an SMS/email challenge code when 2FA requires it.
    async def login(self, user_id: int, username: str, password: str,
                    totp_secret: Optional[str] = None) -> None
        # logs in via instagrapi (in thread):
        #  - if totp_secret: pass verification_code=pyotp.TOTP(secret).now()
        #  - on ChallengeRequired: bridge to code_provider for SMS/email code
        # persists session file on success
    async def publish(self, user_id: int, username: str, password_enc: str,
                      totp_secret_enc: Optional[str], caption: str,
                      image_paths: list[str]) -> dict
        # loads/reuses session (re-login on expiry via decrypted password +
        # totp), photo_upload (1 image) or album_upload (carousel)
    async def logout(self, user_id: int) -> None
        # deletes session file
```

- Session files: `data/ig_session_{user_id}.json`.
- `instagrapi` methods are wrapped in `asyncio.to_thread`.
- Images are downloaded to temp files by the caller (the publisher), paths
  passed in; Instagram deletes them after publish.

### services/publisher.py (new)

```python
@dataclass
class DestResult:
    name: str            # "LinkedIn" / "Instagram"
    ok: bool
    detail: str          # success msg or error

class Publisher:
    def __init__(self, linkedin: LinkedInClient, instagram: InstagramClient,
                 bot: Bot): ...
    async def publish_to_all(self, user: User, text: str,
                             photo_file_ids: list[str]) -> list[DestResult]
```

- Downloads each Telegram photo to a temp file once, reuses paths for all
  destinations, cleans up afterwards.
- Skips a destination if not connected or not enabled (returns a "⏸ off" /
  "not connected" result rather than erroring).
- Re-implements the per-destination upload logic currently duplicated in
  `channel.py`, `post.py`, `approval.py`.

### models.py (modified)

`User` gains:
- `instagram_username: Optional[str] = None`
- `instagram_password_encrypted: Optional[str] = None`
- `instagram_totp_secret_encrypted: Optional[str] = None`
- `linkedin_enabled: bool = True`
- `instagram_enabled: bool = True`

A destination is **connected** when its credential field is set; **enabled** is
the independent toggle.

### services/storage.py (modified)

- New columns on `users` (with idempotent `ALTER TABLE` migrations for existing
  DBs, same pattern already used for `translate_enabled`/`approve_enabled`).
- New methods: `set_instagram_creds(user_id, username, enc_password, enc_totp=None)`,
  `clear_instagram_creds(user_id)`, `set_linkedin_enabled(user_id, bool)`,
  `set_instagram_enabled(user_id, bool)`.

### config.py (modified)

Add `encryption_key: str` (required). `.env.example` documents it.

### bot/handlers/

- **instagram.py (new)**: `/iglogin`, `/iglogout`. `/iglogin` deletes the
  inbound message right after parsing, then runs login and reports outcome.
- **settings.py (modified)**: add `/linkedin on|off`, `/instagram on|off`,
  `/destinations` (status overview).
- **start.py (modified)**: status block now lists both destinations
  (connected/enabled) instead of only LinkedIn.
- **channel.py / post.py / approval.py (modified)**: replace the hard-coded
  LinkedIn publish blocks with a single `publisher.publish_to_all(...)` call
  and render the returned `list[DestResult]`.

## Commands (final set)

| Command | Action |
|---------|--------|
| `/iglogin <user> <pass> [totp_secret]` | Connect Instagram (message auto-deleted) |
| `/iglogout` | Disconnect Instagram (creds + session removed) |
| `/linkedin on\|off` | Toggle LinkedIn publishing |
| `/instagram on\|off` | Toggle Instagram publishing |
| `/destinations` | Show connection + toggle status for both |
| (existing) `/auth`, `/callback`, `/setlang`, `/translate`, `/approve`, etc. | unchanged |

## Error Handling

- Instagram login failure (bad password, network, or 2FA code mismatch after
  the interactive retry) → reported to user; nothing stored.
- Instagram session expiry mid-publish → automatic re-login using the decrypted
  password, then one retry.
- Per-destination failures are isolated: if LinkedIn succeeds but Instagram
  fails, the post is still considered published and the user sees both results.
- Missing `ENCRYPTION_KEY` at startup → bot refuses to start with a clear error.

## Dependencies

- `instagrapi` (new)
- `cryptography` (new, for Fernet)
- `pyotp` (new, for TOTP 2FA code generation)

## Open Risks

- `instagrapi` reverse-engineers Instagram's private API → periodic breakage
  and a non-zero ban risk. Mitigations: reuse stable session files, avoid
  aggressive posting rates, one retry on transient errors only.
