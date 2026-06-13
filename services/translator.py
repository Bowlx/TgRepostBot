import aiohttp


class Translator:
    """
    MyMemory translation API.

    Free, no API key required (5000 chars/day anonymous, 50000 with email).
    API docs: https://mymemory.translated.net/doc/spec.php
    """

    BASE_URL = "https://api.mymemory.translated.net/get"

    def __init__(self, storage=None):
        # storage kept for interface compatibility, MyMemory doesn't need a key
        self.storage = storage

    async def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        if not text.strip():
            return text

        # Optionally use a registered email to raise the daily limit to 50000 chars.
        email = ""
        if self.storage is not None:
            email = (await self.storage.get_setting("mymemory_email")) or ""

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
