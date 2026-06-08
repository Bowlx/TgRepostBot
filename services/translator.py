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
