"""Unit tests for bot/media_group.py — extraction and debounced aggregation."""
import asyncio

import pytest

from bot.media_group import MediaGroupAggregator, extract_group_content

from fakes import make_message


class TestExtractGroupContent:
    def test_sorted_by_message_id(self):
        messages = [
            make_message(3, text="third", media_group_id="g"),
            make_message(1, text="first", media_group_id="g"),
            make_message(2, caption="second", media_group_id="g"),
        ]
        text, photos = extract_group_content(messages)
        assert text == "first\n\nsecond\n\nthird"

    def test_blank_texts_skipped(self):
        messages = [
            make_message(1),
            make_message(2, caption="   "),
            make_message(3, text="only"),
        ]
        text, photos = extract_group_content(messages)
        assert text == "only"
        assert photos == []

    def test_photo_takes_largest_size_file_id(self):
        messages = [make_message(1, photo="abc", caption="cap", media_group_id="g")]
        text, photos = extract_group_content(messages)
        assert text == "cap"
        assert photos == ["abc-large"]


class TestMediaGroupAggregator:
    async def test_group_batched_into_single_callback(self):
        agg = MediaGroupAggregator(delay=0.05)
        done = asyncio.Event()
        calls = []

        async def callback(messages):
            calls.append([m.message_id for m in messages])
            done.set()

        await agg.add(make_message(1, media_group_id="g", photo="a"), callback)
        await agg.add(make_message(2, media_group_id="g", text="t"), callback)
        await asyncio.wait_for(done.wait(), timeout=1)
        assert calls == [[1, 2]]

    async def test_standalone_message_forwarded_immediately(self):
        agg = MediaGroupAggregator(delay=0.05)
        done = asyncio.Event()

        async def callback(messages):
            done.set()

        await agg.add(make_message(1, text="solo"), callback)
        assert done.is_set()  # no debounce delay for standalone messages

    async def test_same_group_in_two_chats_not_mixed(self):
        agg = MediaGroupAggregator(delay=0.05)
        events = {1: asyncio.Event(), 2: asyncio.Event()}
        received = {1: [], 2: []}

        async def callback_chat1(messages):
            received[1].extend(messages)
            events[1].set()

        async def callback_chat2(messages):
            received[2].extend(messages)
            events[2].set()

        await agg.add(make_message(1, media_group_id="g", chat_id=1), callback_chat1)
        await agg.add(make_message(2, media_group_id="g", chat_id=2), callback_chat2)
        await asyncio.wait_for(
            asyncio.gather(events[1].wait(), events[2].wait()), timeout=1
        )
        assert [m.message_id for m in received[1]] == [1]
        assert [m.message_id for m in received[2]] == [2]

    async def test_group_callback_exception_swallowed(self):
        agg = MediaGroupAggregator(delay=0.05)
        processed = asyncio.Event()

        async def callback(messages):
            try:
                raise RuntimeError("callback failed")
            finally:
                processed.set()

        await agg.add(make_message(1, media_group_id="g"), callback)
        task = agg._tasks["42:g"]
        # If the exception were not swallowed by the aggregator, it would
        # surface from awaiting the finalize task and fail the test.
        await asyncio.wait_for(task, timeout=1)
        assert processed.is_set()

    async def test_standalone_callback_exception_propagates(self):
        agg = MediaGroupAggregator(delay=0.05)

        async def callback(messages):
            raise RuntimeError("callback failed")

        with pytest.raises(RuntimeError):
            await agg.add(make_message(1, text="solo"), callback)

    async def test_new_group_message_resets_debounce(self):
        agg = MediaGroupAggregator(delay=0.15)
        done = asyncio.Event()
        calls = []

        async def callback(messages):
            calls.append([m.message_id for m in messages])
            done.set()

        await agg.add(make_message(1, media_group_id="g"), callback)
        key = "42:g"
        first = agg._tasks[key]
        await agg.add(make_message(2, media_group_id="g"), callback)
        await asyncio.sleep(0)
        # Timer reset: the first timer task is no longer running (it
        # suppresses CancelledError, so it ends done() rather than
        # cancelled()) and a fresh task owns the key.
        assert first.done()
        assert agg._tasks[key] is not first
        await asyncio.wait_for(done.wait(), timeout=1)
        assert calls == [[1, 2]]
