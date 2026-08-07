"""Read-only adapter for twitter-cli bookmark JSON."""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Callable


class TwitterCLIError(RuntimeError):
    """A safe, user-facing twitter-cli failure."""


def fetch_bookmarks(
    limit: int,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> object:
    if limit < 1 or limit > 500:
        raise ValueError("Bookmark limit must be between 1 and 500")
    if shutil.which("twitter") is None:
        raise TwitterCLIError(
            "twitter-cli is not installed; install twitter-cli 0.8.5 or newer"
        )
    command = ["twitter", "bookmarks", "-n", str(limit), "--json"]
    result = runner(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        message = (result.stderr or "twitter-cli failed").strip().replace("\n", " ")
        raise TwitterCLIError(message[:500])
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise TwitterCLIError("twitter-cli returned invalid JSON") from error
