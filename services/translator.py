import asyncio
import re

import aiohttp
from deep_translator import GoogleTranslator


class Translator:
    """
    Keyless translation with automatic fallback.

    Primary: deep-translator's GoogleTranslator — scrapes the free Google
    Translate web endpoint (no API key, no credit card, 5000 chars/request).
    Fallback: MyMemory REST API (no key; 500 chars/request, 5000/day anonymous,
    50000/day with /setemail) — used if the Google endpoint is unavailable.
    """

    # Google free endpoint allows ~5000 chars per request (10x MyMemory).
    MAX_QUERY = 5000
    MYMEMORY_URL = "https://api.mymemory.translated.net/get"

    def __init__(self, storage=None):
        # storage is optional; used to read the MyMemory email that lifts the
        # daily limit to 50000 chars (only matters for the fallback path).
        self.storage = storage

    async def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        if not text.strip():
            return text

        chunks = split_text(text, self.MAX_QUERY)
        translated_parts: list[str] = []
        for chunk in chunks:
            translated_parts.append(
                await self._translate_chunk(chunk, source_lang, target_lang)
            )
        return "\n".join(translated_parts)

    async def _translate_chunk(self, text: str, source_lang: str, target_lang: str) -> str:
        # deep-translator is synchronous (uses `requests`); run it in a worker
        # thread so it never blocks the asyncio event loop.
        try:
            return await asyncio.to_thread(
                lambda: GoogleTranslator(source=source_lang, target=target_lang).translate(text)
            )
        except Exception:
            # Google endpoint failed (rate limit / blocked / changed) → MyMemory.
            return await self._mymemory(text, source_lang, target_lang)

    async def _mymemory(self, text: str, source_lang: str, target_lang: str) -> str:
        # MyMemory caps requests at 500 chars, so re-chunk for this path.
        email = ""
        if self.storage is not None:
            email = (await self.storage.get_setting("mymemory_email")) or ""

        parts: list[str] = []
        for sub in split_text(text, 500):
            params = {"q": sub, "langpair": f"{source_lang}|{target_lang}"}
            if email:
                params["de"] = email
            async with aiohttp.ClientSession() as session:
                async with session.get(self.MYMEMORY_URL, params=params) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                    parts.append(data["responseData"]["translatedText"])
        return "\n".join(parts)


# ── Chunking helpers ───────────────────────────────────────


def split_text(text: str, limit: int = 500) -> list[str]:
    """Split text into chunks <= limit chars, preferring paragraph/sentence/word
    boundaries so translations stay coherent and structure is preserved."""
    if len(text) <= limit:
        return [text]

    pieces: list[str] = []
    for line in text.split("\n"):
        if len(line) <= limit:
            pieces.append(line)
        else:
            pieces.extend(_split_by_sentence(line, limit))

    chunks: list[str] = []
    current = ""
    for piece in pieces:
        if not current:
            current = piece
        elif len(current) + 1 + len(piece) <= limit:
            current += "\n" + piece
        else:
            chunks.append(current)
            current = piece
    if current:
        chunks.append(current)
    return [c for c in chunks if c]


def _split_by_sentence(text: str, limit: int) -> list[str]:
    """Split a long line on sentence boundaries (.!?…), then words."""
    sentences = re.split(r"(?<=[.!?…])\s+", text)
    pieces: list[str] = []
    for sent in sentences:
        if len(sent) <= limit:
            pieces.append(sent)
        else:
            pieces.extend(_split_by_words(sent, limit))
    return pieces


def _split_by_words(text: str, limit: int) -> list[str]:
    """Hard-split on word boundaries as a last resort.

    A single token longer than `limit` (e.g. a very long URL) is cut on
    character boundaries — splitting mid-word is ugly but beats failing the
    whole translation.
    """
    words = text.split(" ")
    chunks: list[str] = []
    current = ""
    for word in words:
        token = word
        while len(token) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(token[:limit])
            token = token[limit:]

        if not current:
            current = token
        elif len(current) + 1 + len(token) <= limit:
            current += " " + token
        else:
            chunks.append(current)
            current = token
    if current:
        chunks.append(current)
    return chunks
