"""Unit tests for bot/text_format.py."""
from bot.text_format import MAX_LENGTH, format_text


def test_empty_returns_empty():
    assert format_text("") == ""


def test_rstrips_each_line_preserving_leading_spaces():
    assert format_text("a  \nb\t\n  c") == "a\nb\n  c"


def test_collapses_blank_line_runs():
    assert format_text("a\n\n\n\nb") == "a\n\nb"


def test_strips_outer_whitespace():
    assert format_text("\n\n  a  \n\n") == "a"


def test_over_max_length_truncated_with_ellipsis():
    text = "a" * 2998 + " " + "b" * 500
    result = format_text(text)
    assert len(result) <= MAX_LENGTH
    assert result.endswith("…")
    assert result == "a" * 2998 + "…"


def test_exactly_max_length_unchanged():
    text = "a" * MAX_LENGTH
    assert format_text(text) == text
