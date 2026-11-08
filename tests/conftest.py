from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from whoelse.config import Settings, reset_settings  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def fixtures_built():
    subprocess.run([sys.executable, str(ROOT / "tests" / "make_fixtures.py")], check=True, capture_output=True)


@pytest.fixture(autouse=True)
def offline(tmp_path):
    reset_settings(Settings(home=tmp_path / "home", fixtures_dir=ROOT / "tests" / "fixtures", mailto="", github_token=""))
    yield
    reset_settings(None)
