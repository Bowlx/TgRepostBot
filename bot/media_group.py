"""Aggregate Telegram messages that share a media_group_id into a single unit.

Telegram delivers each message of a media group (album) as a separate update,
all sharing the same `media_group_id`. This module buffers such messages for a
short window, then hands the complete group to a callback — so one album
becomes one LinkedIn post instead of many.
"""
import asyncio
import logging
from collections import defaultdict
from typing import Awaitable, Callable

from aiogram.types import Message

logger = logging.getLogger(__name__)

# Type alias: async callback that receives the full list of messages in a group.
GroupCallback = Callable[[list[Message]], Awaitable[None]]


def extract_group_content(messages: list[Message]) -> tuple[str, list[str]]:
    """Combine text and largest photo from each message, preserving order."""
    ordered = sorted(messages, key=lambda m: m.message_id)
    texts: list[str] = []
    photos: list[str] = []
    for m in ordered:
        text = m.text or m.caption or ""
        if text.strip():
            texts.append(text.strip())
        if m.photo:
            # message.photo is a list of sizes; the last one is the largest.
            photos.append(m.photo[-1].file_id)
    return "\n\n".join(texts), photos


class MediaGroupAggregator:
    """Batches messages sharing a media_group_id, calls callback once per group.

    Standalone messages (no media_group_id) are forwarded immediately.
    """

    def __init__(self, delay: float = 1.0):
        self.delay = delay
        self._buffers: dict[str, list[Message]] = defaultdict(list)
        self._tasks: dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()

    async def add(self, message: Message, callback: GroupCallback) -> None:
        group_id = message.media_group_id
        if group_id is None:
            # Standalone message — process immediately as a single-item group.
            await callback([message])
            return

        # Key by chat + group so two chats with the same group id never mix.
        key = f"{message.chat.id}:{group_id}"

        async with self._lock:
            self._buffers[key].append(message)
            # Reset the timer for this group (a new message arrived).
            existing = self._tasks.get(key)
            if existing is not None:
                existing.cancel()
            self._tasks[key] = asyncio.create_task(self._finalize(key, callback))

    async def _finalize(self, key: str, callback: GroupCallback) -> None:
        try:
            await asyncio.sleep(self.delay)
        except asyncio.CancelledError:
            return

        async with self._lock:
            messages = self._buffers.pop(key, [])
            self._tasks.pop(key, None)

        if not messages:
            return

        try:
            await callback(messages)
        except Exception:
            logger.exception("Error processing media group %s", key)
