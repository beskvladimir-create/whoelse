"""Runtime configuration. Everything lives in one local folder; nothing leaves the machine
except the API calls to public, open data sources."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _default_home() -> Path:
    env = os.environ.get("WHOELSE_HOME")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".whoelse"


@dataclass
class Settings:
    home: Path = field(default_factory=_default_home)
    # OpenAlex "polite pool": an email in the request gets you faster, more reliable responses.
    # It is only ever sent to api.openalex.org. Leave empty to stay anonymous.
    mailto: str = field(default_factory=lambda: os.environ.get("WHOELSE_MAILTO", ""))
    # Optional GitHub token raises the search rate limit from 10 to 30 requests/min.
    github_token: str = field(default_factory=lambda: os.environ.get("GITHUB_TOKEN", ""))
    # How far back "working on it now" reaches, in months.
    recent_months: int = field(default_factory=lambda: int(os.environ.get("WHOELSE_RECENT_MONTHS", "24")))
    # Cache TTL for HTTP responses, in hours.
    cache_hours: int = field(default_factory=lambda: int(os.environ.get("WHOELSE_CACHE_HOURS", "72")))
    # When set, the HTTP layer answers from this folder of recorded responses and never touches the network.
    fixtures_dir: Path | None = field(
        default_factory=lambda: Path(os.environ["WHOELSE_FIXTURES"]) if os.environ.get("WHOELSE_FIXTURES") else None
    )
    user_agent: str = "whoelse/0.1 (+https://github.com/besk-tech/whoelse)"

    @property
    def cache_dir(self) -> Path:
        return self.home / "cache"

    @property
    def profiles_dir(self) -> Path:
        return self.home / "profiles"

    def ensure(self) -> "Settings":
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.profiles_dir.mkdir(parents=True, exist_ok=True)
        return self


_settings: Settings | None = None


def settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings().ensure()
    return _settings


def reset_settings(new: Settings | None = None) -> None:
    """Used by tests."""
    global _settings
    _settings = new.ensure() if new else None
