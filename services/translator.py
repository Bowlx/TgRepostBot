from typing import TYPE_CHECKING

import aiohttp

if TYPE_CHECKING:
    from services.storage import Storage


class Translator:
    BASE_URL = "https://translation.googleapis.com/language/translate/v2"

    def __init__(self, storage: "Storage"):
        self.storage = storage

    async def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        if not text.strip():
            return text

        api_key = await self.storage.get_setting("google_translate_api_key")
        if not api_key:
            raise RuntimeError(
                "Ключ Google Translate не настроен. Используйте /setup"
            )

        params = {
            "key": api_key,
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
