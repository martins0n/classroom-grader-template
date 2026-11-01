import os
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture
def sandbox_ready():
    """Docker tests run on a real GitHub runner. There, skipping them would be a false pass."""
    if shutil.which("docker") and os.environ.get("SANDBOX_DEPS_DIR"):
        return
    message = "needs Docker and SANDBOX_DEPS_DIR (runs in the 'Selftest: sandbox' workflow)"
    if os.environ.get("REQUIRE_SANDBOX_TESTS"):
        pytest.fail(message)
    pytest.skip(message)


def write_notebook(path: Path, *cells: str) -> Path:
    import json

    path.write_text(json.dumps({
        "cells": [
            {"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": source}
            for source in cells
        ],
        "metadata": {},
        "nbformat": 4,
        "nbformat_minor": 4,
    }))
    return path
