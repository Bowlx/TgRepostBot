"""Unit tests for clean_totp_secret in services/instagram.py."""
import base64

import pytest

from services.instagram import clean_totp_secret


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("gezd gnb", "GEZDGNB="),
        ("gezdgnb", "GEZDGNB="),
        ("Gezd Gnb", "GEZDGNB="),
        ("gezdgnb =", "GEZDGNB="),
        ("JBSWY3DPEHPK3PXP", "JBSWY3DPEHPK3PXP"),  # already a multiple of 8
        ("otpauth://totp/Instagram:user?secret=abcde&issuer=IG", "ABCDE==="),
        ("  abcde  ", "ABCDE==="),
    ],
)
def test_normalizes_input(raw, expected):
    assert clean_totp_secret(raw) == expected
    # The whole point of the function is to produce a decodable secret.
    base64.b32decode(expected)


@pytest.mark.parametrize("raw", ["", "   ", "123", "abc!", "gezdgnbgy1"])
def test_invalid_input_raises(raw):
    with pytest.raises(ValueError):
        clean_totp_secret(raw)


# Data lengths that no valid base32 string can have (a final 8-char block
# carries 2, 4, 5 or 7 data chars). clean_totp_secret pads mechanically
# without validating the length, so these DO NOT raise.
@pytest.mark.xfail(strict=True, reason="clean_totp_secret does not validate base32 length")
def test_invalid_base32_length_raises():
    for raw in ["gezdgnbgy", "abc256", "a"]:
        with pytest.raises(ValueError):
            clean_totp_secret(raw)
