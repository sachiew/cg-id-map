"""HTTP client with per-provider rate limiting, retries with backoff, and a timestamped disk cache.

Request headers (which carry API keys) are never logged or cached. Logs show the path only.
"""

from __future__ import annotations

import hashlib
import json
import logging
import ssl
import time
from collections.abc import Iterator, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import truststore

log = logging.getLogger(__name__)
# httpx logs full URLs at INFO; keep it quiet so query strings never reach logs.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

RETRY_STATUS = frozenset({429, 500, 502, 503, 504})


class ApiError(RuntimeError):
    pass


class RateLimiter:
    def __init__(self, per_minute: float) -> None:
        self.interval = 60.0 / per_minute if per_minute > 0 else 0.0
        self._next = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        if now < self._next:
            time.sleep(self._next - now)
        self._next = max(now, self._next) + self.interval


class HttpClient:
    def __init__(
        self,
        provider: str,
        *,
        headers: Mapping[str, str] | None = None,
        rate_per_min: float,
        cache_dir: Path | None,
        cache_max_age_hours: float = 20.0,
        max_retries: int = 5,
        timeout_s: float = 60.0,
        transport: httpx.BaseTransport | None = None,
        refresh: bool = False,
    ) -> None:
        self.provider = provider
        self.limiter = RateLimiter(rate_per_min)
        self.cache_dir = cache_dir / provider if cache_dir else None
        self.cache_max_age_s = cache_max_age_hours * 3600
        self.max_retries = max_retries
        self.refresh = refresh
        # OS trust store: works behind TLS-inspecting proxies whose root is installed system-wide.
        verify: ssl.SSLContext | bool = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self._client = httpx.Client(
            headers=dict(headers or {}),
            timeout=timeout_s,
            transport=transport,
            verify=verify,
        )

    def close(self) -> None:
        self._client.close()

    # ------------------------------------------------------------------ cache

    def _cache_path(self, url: str, params: Mapping[str, Any]) -> Path | None:
        if not self.cache_dir:
            return None
        key = json.dumps([url, sorted((k, str(v)) for k, v in params.items())])
        digest = hashlib.sha256(key.encode()).hexdigest()[:20]
        return self.cache_dir / f"{digest}.json"

    def _cache_read(self, path: Path | None) -> Any | None:
        if path is None or self.refresh or not path.is_file():
            return None
        entry = json.loads(path.read_text())
        fetched = datetime.fromisoformat(entry["fetched_at"])
        if (datetime.now(UTC) - fetched).total_seconds() > self.cache_max_age_s:
            return None
        return entry["data"]

    def _cache_write(
        self, path: Path | None, url: str, params: Mapping[str, Any], data: Any
    ) -> None:
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "fetched_at": datetime.now(UTC).isoformat(),
            "url": url,  # never includes keys: keys travel in headers only
            "params": {k: str(v) for k, v in params.items()},
            "data": data,
        }
        path.write_text(json.dumps(entry))

    # ------------------------------------------------------------------ requests

    def get_json(self, url: str, params: Mapping[str, Any] | None = None) -> Any:
        params = dict(params or {})
        path = self._cache_path(url, params)
        cached = self._cache_read(path)
        if cached is not None:
            return cached
        data = self._get_with_retries(url, params)
        self._cache_write(path, url, params, data)
        return data

    def _get_with_retries(self, url: str, params: dict[str, Any]) -> Any:
        shown = httpx.URL(url).path
        for attempt in range(self.max_retries + 1):
            self.limiter.wait()
            try:
                resp = self._client.get(url, params=params)
            except httpx.TransportError as exc:
                if attempt == self.max_retries:
                    raise ApiError(f"{self.provider} GET {shown}: {type(exc).__name__}") from None
                self._sleep_backoff(attempt, None, shown, type(exc).__name__)
                continue
            if resp.status_code in RETRY_STATUS and attempt < self.max_retries:
                self._sleep_backoff(
                    attempt, resp.headers.get("retry-after"), shown, resp.status_code
                )
                continue
            if resp.status_code != 200:
                raise ApiError(
                    f"{self.provider} GET {shown}: HTTP {resp.status_code} {_snippet(resp)}"
                )
            return resp.json()
        raise ApiError(f"{self.provider} GET {shown}: retries exhausted")  # pragma: no cover

    def _sleep_backoff(
        self, attempt: int, retry_after: str | None, shown: str, why: object
    ) -> None:
        delay = min(2.0**attempt * 5, 120.0)
        if retry_after and retry_after.isdigit():
            delay = max(delay, float(retry_after))
        log.warning(
            "%s GET %s -> %s; retry %d in %.0fs", self.provider, shown, why, attempt + 1, delay
        )
        time.sleep(delay)


def _snippet(resp: httpx.Response) -> str:
    # Error bodies from these APIs are short status objects; they never echo request headers.
    return resp.text[:200].replace("\n", " ")


def batch_ids(ids: Sequence[str], max_n: int, max_chars: int) -> Iterator[list[str]]:
    """Split IDs into batches bounded by count and by joined length (URL length limits)."""
    batch: list[str] = []
    size = 0
    for i in ids:
        if batch and (len(batch) >= max_n or size + len(i) + 1 > max_chars):
            yield batch
            batch, size = [], 0
        batch.append(i)
        size += len(i) + 1
    if batch:
        yield batch
