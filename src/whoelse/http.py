"""One polite HTTP client for every source: on-disk cache, retries, rate-limit backoff,
and a fixtures mode for tests and offline demos."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

from .config import settings


class SourceError(RuntimeError):
    """A data source could not answer. Carries enough to tell the user what happened."""


def _cache_key(url: str, params: dict[str, Any] | None, headers_sig: str) -> str:
    raw = url + "?" + urlencode(sorted((params or {}).items()), doseq=True) + "|" + headers_sig
    return hashlib.sha256(raw.encode()).hexdigest()


class Http:
    def __init__(self, *, timeout: float = 30.0) -> None:
        self._client: httpx.AsyncClient | None = None
        self._timeout = timeout
        self._lock = asyncio.Lock()

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                headers={"User-Agent": settings().user_agent, "Accept": "application/json"},
                follow_redirects=True,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _fixture(self, url: str, params: dict[str, Any] | None) -> Any | None:
        fx = settings().fixtures_dir
        if not fx:
            return None
        key = _cache_key(url, params, "")
        path = fx / f"{key}.json"
        if path.exists():
            return json.loads(path.read_text())
        index = fx / "index.json"
        if index.exists():
            # index.json maps a human-readable key ("openalex:works:text-to-sql") to a file name.
            # Sources register their lookups by passing fixture_name; see get_json.
            return None
        return None

    async def get_json(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        *,
        headers: dict[str, str] | None = None,
        fixture_name: str | None = None,
        accept: str = "application/json",
    ) -> Any:
        """GET and parse JSON (or raw text when accept != json). Cached on disk by URL+params."""
        s = settings()
        if s.fixtures_dir:
            if fixture_name:
                p = s.fixtures_dir / f"{fixture_name}.json"
                if p.exists():
                    data = json.loads(p.read_text())
                    return data.get("__text__", data) if accept != "application/json" else data
            fx = self._fixture(url, params)
            if fx is not None:
                return fx
            raise SourceError(f"offline: no fixture for {fixture_name or url}")

        headers_sig = (headers or {}).get("Authorization", "")[:8]
        key = _cache_key(url, params, headers_sig)
        cache_path = s.cache_dir / f"{key}.json"
        if cache_path.exists():
            age_h = (time.time() - cache_path.stat().st_mtime) / 3600
            if age_h < s.cache_hours:
                try:
                    cached = json.loads(cache_path.read_text())
                    return cached.get("__text__", cached) if accept != "application/json" else cached
                except json.JSONDecodeError:
                    pass

        client = await self._get_client()
        req_headers = {"Accept": accept}
        if headers:
            req_headers.update(headers)
        last_exc: Exception | None = None
        for attempt in range(4):
            try:
                r = await client.get(url, params=params, headers=req_headers)
                if r.status_code == 429 or r.status_code >= 500:
                    wait = float(r.headers.get("Retry-After", 2 ** attempt))
                    await asyncio.sleep(min(wait, 30))
                    continue
                if r.status_code == 404:
                    return None
                r.raise_for_status()
                if accept == "application/json":
                    data = r.json()
                    cache_path.write_text(json.dumps(data))
                    return data
                text = r.text
                cache_path.write_text(json.dumps({"__text__": text}))
                return text
            except (httpx.TransportError, httpx.HTTPStatusError) as e:
                last_exc = e
                await asyncio.sleep(2 ** attempt)
        raise SourceError(f"{url}: {last_exc}")


http = Http()
