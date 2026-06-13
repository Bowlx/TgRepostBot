from typing import TYPE_CHECKING

import aiohttp

if TYPE_CHECKING:
    from services.storage import Storage


class Translator:
    # DeepL API Free uses a different host than the paid API
    BASE_URL = "https://api-free.deepl.com/v2/translate"

    def __init__(self, storage: "Storage"):
        self.storage = storage

    async def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        if not text.strip():
            return text

        api_key = await self.storage.get_setting("deepl_api_key")
        if not api_key:
            raise RuntimeError(
                "Ключ DeepL не настроен. Используйте /setup"
            )

        data = {
            "auth_key": api_key,
            "text": text,
            "source_lang": source_lang.upper(),
            "target_lang": target_lang.upper(),
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(self.BASE_URL, data=data) as resp:
                resp.raise_for_status()
                result = await resp.json()
                return result["translations"][0]["text"]
