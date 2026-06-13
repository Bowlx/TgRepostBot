import re

import aiohttp


class Translator:
    """
    MyMemory translation API.

    Free, no API key required (5000 chars/day anonymous, 50000 with email).
    MyMemory caps a single request at 500 chars, so we chunk long texts on
    paragraph/sentence boundaries, translate each piece, and rejoin them.
    API docs: https://mymemory.translated.net/doc/spec.php
    """

    BASE_URL = "https://api.mymemory.translated.net/get"
    MAX_QUERY = 500  # MyMemory per-request limit (chars)

    def __init__(self, storage=None):
        # storage kept for interface compatibility (optional email to lift daily limit)
        self.storage = storage

    async def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        if not text.strip():
            return text

        email = ""
        if self.storage is not None:
            email = (await self.storage.get_setting("mymemory_email")) or ""

        chunks = split_text(text, self.MAX_QUERY)
        translated_parts: list[str] = []
        for chunk in chunks:
            translated_parts.append(
                await self._translate_chunk(chunk, source_lang, target_lang, email)
            )
        return "\n".join(translated_parts)

    async def _translate_chunk(
        self, text: str, source_lang: str, target_lang: str, email: str
    ) -> str:
        params = {
            "q": text,
            "langpair": f"{source_lang}|{target_lang}",
        }
        if email:
            params["de"] = email

        async with aiohttp.ClientSession() as session:
            async with session.get(self.BASE_URL, params=params) as resp:
                resp.raise_for_status()
                data = await resp.json()
                return data["responseData"]["translatedText"]


# ── Chunking helpers ───────────────────────────────────────


def split_text(text: str, limit: int = 500) -> list[str]:
    """Split text into chunks <= limit chars, preferring paragraph/sentence/word
    boundaries so translations stay coherent and structure is preserved."""
    if len(text) <= limit:
        return [text]

    # 1) Break on newlines (paragraphs/lines).
    pieces: list[str] = []
    for line in text.split("\n"):
        if len(line) <= limit:
            pieces.append(line)
        else:
            pieces.extend(_split_by_sentence(line, limit))

    # 2) Greedily pack pieces back into chunks <= limit.
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
    """Split a long line on sentence boundaries (.!?), then words."""
    sentences = re.split(r"(?<=[.!?…])\s+", text)
    pieces: list[str] = []
    for sent in sentences:
        if len(sent) <= limit:
            pieces.append(sent)
        else:
            pieces.extend(_split_by_words(sent, limit))
    return pieces


def _split_by_words(text: str, limit: int) -> list[str]:
    """Hard-split on word boundaries as a last resort."""
    words = text.split(" ")
    chunks: list[str] = []
    current = ""
    for word in words:
        if not current:
            current = word
        elif len(current) + 1 + len(word) <= limit:
            current += " " + word
        else:
            chunks.append(current)
            current = word
    if current:
        chunks.append(current)
    return chunks
