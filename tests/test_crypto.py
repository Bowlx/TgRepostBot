"""Unit tests for services/crypto.py."""
import pytest
from cryptography.fernet import Fernet, InvalidToken

from services.crypto import Crypto

KEY_1 = Fernet.generate_key().decode()
KEY_2 = Fernet.generate_key().decode()


@pytest.mark.parametrize(
    "plaintext",
    ["plain-secret", "пароль-с-кириллицей", "emoji 🔑 secret", ""],
)
def test_roundtrip(plaintext):
    crypto = Crypto(KEY_1)
    assert crypto.decrypt(crypto.encrypt(plaintext)) == plaintext


def test_wrong_key_rejected():
    token = Crypto(KEY_1).encrypt("secret")
    with pytest.raises(InvalidToken):
        Crypto(KEY_2).decrypt(token)


def test_malformed_key_rejected_at_construction():
    with pytest.raises(ValueError):
        Crypto("not-a-valid-fernet-key")
