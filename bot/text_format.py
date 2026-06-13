"""Light text cleanup applied to a post body before publishing to LinkedIn.

Strips Telegram-side noise (leading/trailing whitespace, runs of blank lines,
trailing spaces on each line) without touching the meaning. LinkedIn rejects
posts over 3000 chars, so we also hard-cap length.
"""
import re

MAX_LENGTH = 3000


def format_text(text: str) -> str:
    if not text:
        return ""
    # Strip trailing whitespace from each line.
    lines = [line.rstrip() for line in text.splitlines()]
    cleaned = "\n".join(lines)
    # Collapse 3+ consecutive newlines into exactly 2 (one blank line).
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = cleaned.strip()
    if len(cleaned) > MAX_LENGTH:
        cleaned = cleaned[:MAX_LENGTH - 1].rstrip() + "…"
    return cleaned
