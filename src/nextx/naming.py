"""Stable, portable filenames for newly captured Signal notes."""

from __future__ import annotations

from datetime import datetime
import hashlib
import re
import unicodedata


PORTABLE_FILENAME_BYTES = 240
_UNSAFE_FILENAME_CHARS = frozenset('/\\:*?"<>|')


def signal_display_title(text: str) -> str:
    """Return the first non-empty, whitespace-normalized line, max 100 chars."""
    for line in text.splitlines():
        normalized = " ".join(line.split())
        if normalized:
            return normalized[:100]
    return ""


def safe_filename_component(value: str, *, fallback: str) -> str:
    """Normalize Unicode and replace separators, controls, and reserved punctuation."""
    normalized = unicodedata.normalize("NFKC", value if isinstance(value, str) else "")
    cleaned = "".join(
        " " if char in _UNSAFE_FILENAME_CHARS or unicodedata.category(char).startswith("C") else char
        for char in normalized
    )
    safe = re.sub(r"\s+", "-", cleaned).strip(".-@ ")
    while ".." in safe:
        safe = safe.replace("..", "-")
    return safe or fallback


def human_signal_filename(
    *,
    signal_id: str,
    platform: str,
    author_handle: str | None,
    observed_at: str,
    display_title: str,
) -> str:
    """Build DATE__PLATFORM__AUTHOR__TITLE__UNIQUE.md within 240 UTF-8 bytes."""
    observed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    date = observed.date().isoformat()
    safe_platform = safe_filename_component(platform, fallback="unknown-platform")
    safe_author = safe_filename_component(author_handle or "", fallback="unknown-author")
    title = safe_filename_component(display_title, fallback="untitled")
    x_identifier = re.fullmatch(r"x:(\d+)", signal_id)
    unique = (
        x_identifier.group(1)
        if x_identifier
        else hashlib.sha256(signal_id.encode("utf-8")).hexdigest()[:8]
    )

    prefix = f"{date}__{safe_platform}__{safe_author}__"
    suffix = f"__{unique}.md"
    if len((prefix + suffix).encode("utf-8")) > PORTABLE_FILENAME_BYTES:
        raise ValueError("Signal filename fixed components exceed portable byte limit")
    while len((prefix + title + suffix).encode("utf-8")) > PORTABLE_FILENAME_BYTES and title:
        title = title[:-1]
    if not title:
        raise ValueError("Signal filename title cannot fit within portable byte limit")
    return prefix + title + suffix
