"""Unit tests for services/translator.py — chunking and fallback wiring, no network."""
import re

import pytest

import services.translator
from services.translator import Translator, split_text


class TestSplitText:
    def test_short_text_unchanged(self):
        assert split_text("hello world", 5000) == ["hello world"]

    def test_long_text_chunks_within_limit(self):
        text = "\n".join(f"предложение номер {i}." for i in range(200))
        chunks = split_text(text, 200)
        assert len(chunks) > 1
        assert all(len(chunk) <= 200 for chunk in chunks)
        # Chunk boundaries may drop the joining whitespace; non-whitespace
        # content must survive intact.
        assert re.sub(r"\s+", "", "".join(chunks)) == re.sub(r"\s+", "", text)

    def test_prefers_paragraph_boundaries(self):
        paragraphs = ["слово " * 5 for _ in range(5)]  # 30 chars each
        text = "\n".join(paragraphs)
        chunks = split_text(text, 50)
        assert chunks == paragraphs  # pairs (30 + 1 + 30 > 50) never share a chunk

    def test_short_paragraphs_merged_into_single_chunk(self):
        paragraphs = ["слово " * 5 for _ in range(2)]  # 30 chars each, 61 total
        text = "\n".join(paragraphs)
        assert split_text(text, 100) == [text]

    def test_single_token_longer_than_limit_cut_by_chars(self):
        url = "https://example.com/very/long/path/segments"
        chunks = split_text(url, 10)
        assert all(len(chunk) <= 10 for chunk in chunks)
        assert "".join(chunks) == url


class TestTranslate:
    async def test_empty_and_whitespace_returned_as_is(self, monkeypatch):
        async def fail(self, chunk, source_lang, target_lang):
            raise AssertionError("translation backend reached for empty input")

        monkeypatch.setattr(Translator, "_translate_chunk", fail)
        translator = Translator()
        assert await translator.translate("", "ru", "en") == ""
        assert await translator.translate("  \n\t ", "ru", "en") == "  \n\t "

    async def test_long_text_assembled_from_chunks(self, monkeypatch):
        text = "абзац с текстом. " * 600  # > MAX_QUERY
        chunks = split_text(text, Translator.MAX_QUERY)
        calls = []

        async def identity(self, chunk, source_lang, target_lang):
            calls.append(chunk)
            return chunk

        monkeypatch.setattr(Translator, "_translate_chunk", identity)
        result = await Translator().translate(text, "ru", "en")
        assert result == "\n".join(chunks)
        assert calls == chunks

    async def test_google_failure_falls_back_to_mymemory(self, monkeypatch):
        class BlockedGoogle:
            def __init__(self, source, target):
                pass

            def translate(self, text):
                raise RuntimeError("endpoint blocked")

        monkeypatch.setattr(services.translator, "GoogleTranslator", BlockedGoogle)
        fallback_calls = []

        async def fake_mymemory(self, text, source_lang, target_lang):
            fallback_calls.append((text, source_lang, target_lang))
            return "MM"

        monkeypatch.setattr(Translator, "_mymemory", fake_mymemory)
        result = await Translator().translate("привет", "ru", "en")
        assert result == "MM"
        assert fallback_calls == [("привет", "ru", "en")]
