"""Shared fixtures for the TgRepostBot test suite. Fakes live in fakes.py."""
import socket

import pytest

from fakes import FakeBot, FakeInstagram, FakeLinkedIn
from services.publisher import Publisher
from services.storage import Storage


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    """Fail fast on any outbound connection — tests must not touch the network."""

    def denied_connect(self, address):
        raise AssertionError(f"network access in tests: {address!r}")

    monkeypatch.setattr(socket.socket, "connect", denied_connect)


@pytest.fixture
async def storage(tmp_path):
    storage = Storage(str(tmp_path / "test.db"))
    await storage.init()
    return storage


@pytest.fixture
def make_publisher():
    def _make(*, bot=None, linkedin=None, instagram=None) -> Publisher:
        return Publisher(
            linkedin=linkedin or FakeLinkedIn(),
            instagram=instagram or FakeInstagram(),
            bot=bot or FakeBot(),
        )

    return _make
