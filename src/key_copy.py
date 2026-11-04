"""The teacher's copy of a course's encryption key, on the teacher's own machine.

GitHub never shows a secret again, so this copy is the only way to read stored work later.
A key file on a runner is how the old pipeline leaked its key, so saving one and exporting
work both refuse to run in CI.
"""
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from src.encryption import load_master_key


def refuse_in_ci() -> None:
    if os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"):
        raise SystemExit("Refusing to run in CI: keys and decrypted work must stay off runners.")


def key_path(repo: str) -> Path:
    return Path.home() / ".config" / "classroom-grader" / f"{repo.replace('/', '__')}.key"


def save_key_copy(repo: str, key: str) -> Path:
    """Store a new key. A previous copy stays beside it, because old versions still need it."""
    refuse_in_ci()
    path = key_path(repo)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        path.rename(path.with_name(f"{path.name}.{stamp}"))
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        handle.write(key + "\n")
    return path


def load_key_copies(repo: str) -> List[bytes]:
    """Every saved key of this course, current and rotated."""
    path = key_path(repo)
    return [load_master_key(item.read_text()) for item in sorted(path.parent.glob(f"{path.name}*"))]
