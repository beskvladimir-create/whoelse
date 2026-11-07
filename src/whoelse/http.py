"""One polite HTTP client for every source: on-disk cache, retries, rate-limit backoff,
and a fixtures mode for tests and offline demos."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx

from .config import settings


class SourceError(RuntimeError):
    """A data source could not answer. Carries enough to tell the user what happened."""


def _cache_key(url: str, params: dict[str, Any] | None, headers_sig: str, accept: str = "") -> str:
    raw = url + "?" + urlencode(sorted((params or {}).items()), doseq=True) + "|" + headers_sig + "|" + accept
    return hashlib.sha256(raw.encode()).hexdigest()


def _safe_name(name: str) -> str:
    return re.sub(r"[^\w.-]", "_", name)[:150]


def _retry_after(value: str | None, attempt: int) -> float:
    if not value:
        return float(2 ** attempt)
    try:
        return min(float(value), 60.0)
    except ValueError:
        try:
            dt = parsedate_to_datetime(value)
            return max(1.0, min((dt - datetime.now(timezone.utc)).total_seconds(), 60.0))
        except (TypeError, ValueError):
            return float(2 ** attempt)


class Http:
    # Polite concurrency per host: public APIs are shared with everyone.
    PER_HOST = {"api.github.com": 2, "api.openalex.org": 4, "pub.orcid.org": 4, "export.arxiv.org": 1, "huggingface.co": 4}

    def __init__(self, *, timeout: float = 30.0) -> None:
        self._client: httpx.AsyncClient | None = None
        self._timeout = timeout
        self._sems: dict[str, asyncio.Semaphore] = {}

    def _sem(self, url: str) -> asyncio.Semaphore:
        host = urlsplit(url).netloc
        loop_id = id(asyncio.get_running_loop())
        key = f"{loop_id}:{host}"
        if key not in self._sems:
            self._sems[key] = asyncio.Semaphore(self.PER_HOST.get(host, 3))
        return self._sems[key]

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
        want_json = accept == "application/json"
        if s.fixtures_dir:
            if fixture_name:
                p = s.fixtures_dir / f"{_safe_name(fixture_name)}.json"
                if p.exists():
                    data = json.loads(p.read_text())
                    if isinstance(data, dict) and "__text__" in data:
                        return data["__text__"]
                    return data
            raise SourceError(f"offline: no fixture for {fixture_name or url}")

        headers_sig = (headers or {}).get("Authorization", "")[:8]
        key = _cache_key(url, params, headers_sig, accept)
        cache_path = s.cache_dir / f"{key}.json"
        if cache_path.exists():
            age_h = (time.time() - cache_path.stat().st_mtime) / 3600
            if age_h < s.cache_hours:
                try:
                    cached = json.loads(cache_path.read_text())
                    if isinstance(cached, dict) and "__text__" in cached:
                        return cached["__text__"]
                    return cached
                except json.JSONDecodeError:
                    pass

        client = await self._get_client()
        req_headers = {"Accept": accept}
        if headers:
            req_headers.update(headers)
        last: str = "no attempt"
        async with self._sem(url):
            for attempt in range(4):
                try:
                    r = await client.get(url, params=params, headers=req_headers)
                except httpx.TransportError as e:
                    last = f"transport error: {e}"
                    await asyncio.sleep(2 ** attempt)
                    continue
                if r.status_code == 404:
                    return None
                if r.status_code == 429 or r.status_code >= 500 or (
                    r.status_code == 403 and (r.headers.get("X-RateLimit-Remaining") == "0" or r.headers.get("Retry-After"))
                ):
                    last = f"HTTP {r.status_code}"
                    wait = _retry_after(r.headers.get("Retry-After"), attempt)
                    reset = r.headers.get("X-RateLimit-Reset")
                    if reset and r.status_code == 403:
                        try:
                            wait = max(wait, min(float(reset) - time.time(), 60.0))
                        except ValueError:
                            pass
                    await asyncio.sleep(wait)
                    continue
                if r.status_code >= 400:
                    raise SourceError(f"{url}: HTTP {r.status_code}")
                if want_json:
                    try:
                        data = r.json()
                    except ValueError as e:
                        raise SourceError(f"{url}: response is not JSON ({e})")
                    cache_path.write_text(json.dumps(data))
                    return data
                text = r.text
                cache_path.write_text(json.dumps({"__text__": text}))
                return text
        raise SourceError(f"{url}: gave up after 4 attempts ({last})")


http = Http()
