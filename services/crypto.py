from cryptography.fernet import Fernet


class Crypto:
    """Symmetric encryption (Fernet) for secrets stored at rest.

    Used for the Instagram password and optional TOTP secret. The key comes
    from ENCRYPTION_KEY in .env; without it the bot refuses to start.
    """

    def __init__(self, key: str):
        # Raises if the key is malformed — surfaces at startup, not at use.
        self._fernet = Fernet(key.encode() if isinstance(key, str) else key)

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, token: str) -> str:
        return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")