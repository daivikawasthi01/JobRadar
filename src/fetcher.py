"""HTTP fetcher with async concurrency, rate limits, retries, and backoff."""
import asyncio
import json
import logging
import random
from typing import Any
import aiohttp

logger = logging.getLogger(__name__)


class FetchError(Exception):
    """Raised on HTTP fetch failure or invalid JSON."""
    pass


class NotFoundError(FetchError):
    """Raised immediately when an endpoint returns HTTP 404."""
    pass


async def get_json(
    session: aiohttp.ClientSession,
    url: str,
    *,
    method: str = "GET",
    json_body: Any = None,
    timeout_seconds: float = 15.0,
    retries: int = 3,
    semaphore: asyncio.Semaphore | None = None,
) -> Any:
    """Fetch JSON from a URL with retry logic, backoff, and 404 handling.

    - Retries on: timeouts, connection errors, HTTP 429, HTTP 5xx.
    - Backoff: 1s, 2s, 4s plus random jitter (0-0.5s).
    - If Retry-After is present on HTTP 429: wait that many seconds (capped at 30s).
    - HTTP 404 -> raises NotFoundError immediately without retry.
    - Other 4xx -> raises FetchError without retry.
    - Invalid JSON -> raises FetchError.
    """
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)

    async def _do_fetch() -> Any:
        attempt = 0
        while True:
            try:
                kwargs: dict[str, Any] = {"timeout": timeout}
                if json_body is not None:
                    kwargs["json"] = json_body

                async with session.request(method, url, **kwargs) as resp:
                    status = resp.status

                    # 404 -> immediate NotFoundError
                    if status == 404:
                        raise NotFoundError(f"HTTP 404 Not Found: {url}")

                    # 2xx -> parse JSON
                    if 200 <= status < 300:
                        try:
                            return await resp.json(content_type=None)
                        except (aiohttp.ContentTypeError, json.JSONDecodeError, UnicodeDecodeError) as e:
                            raise FetchError(f"Invalid JSON from {url}: {e}") from e

                    # 429 -> Rate limited (retryable)
                    if status == 429:
                        attempt += 1
                        if attempt > retries:
                            raise FetchError(f"HTTP 429 Rate limited at {url} after {retries} retries")

                        retry_after_hdr = resp.headers.get("Retry-After")
                        wait_time: float = 0.0
                        if retry_after_hdr:
                            try:
                                wait_time = min(float(retry_after_hdr), 30.0)
                            except ValueError:
                                wait_time = 0.0

                        if wait_time <= 0:
                            wait_time = (2 ** (attempt - 1)) + random.uniform(0.0, 0.5)

                        logger.warning("HTTP 429 for %s; waiting %.1fs (attempt %d/%d)", url, wait_time, attempt, retries)
                        await asyncio.sleep(wait_time)
                        continue

                    # 5xx -> Server error (retryable)
                    if 500 <= status < 600:
                        attempt += 1
                        if attempt > retries:
                            raise FetchError(f"HTTP {status} server error at {url} after {retries} retries")

                        wait_time = (2 ** (attempt - 1)) + random.uniform(0.0, 0.5)
                        logger.warning("HTTP %d for %s; waiting %.1fs (attempt %d/%d)", status, url, wait_time, attempt, retries)
                        await asyncio.sleep(wait_time)
                        continue

                    # Other 4xx -> client error (not retryable)
                    text = await resp.text()
                    raise FetchError(f"HTTP {status} Client Error at {url}: {text[:200]}")

            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                if isinstance(exc, (NotFoundError, FetchError)):
                    raise

                attempt += 1
                if attempt > retries:
                    raise FetchError(f"Network error at {url} after {retries} retries: {exc}") from exc

                wait_time = (2 ** (attempt - 1)) + random.uniform(0.0, 0.5)
                logger.warning("Network error (%s) for %s; waiting %.1fs (attempt %d/%d)", exc, url, wait_time, attempt, retries)
                await asyncio.sleep(wait_time)

    if semaphore is not None:
        async with semaphore:
            return await _do_fetch()
    return await _do_fetch()


async def get_text(
    session: aiohttp.ClientSession,
    url: str,
    *,
    timeout_seconds: float = 15.0,
    retries: int = 3,
    semaphore: asyncio.Semaphore | None = None,
) -> str:
    """Fetch plain text with the same retry and status handling as get_json."""
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)

    async def _do_fetch() -> str:
        attempt = 0
        while True:
            try:
                async with session.request("GET", url, timeout=timeout) as resp:
                    status = resp.status
                    if status == 404:
                        raise NotFoundError(f"HTTP 404 Not Found: {url}")
                    if 200 <= status < 300:
                        return await resp.text()

                    if status == 429 or 500 <= status < 600:
                        attempt += 1
                        if attempt > retries:
                            raise FetchError(
                                f"HTTP {status} error at {url} after {retries} retries"
                            )

                        wait_time = 0.0
                        if status == 429:
                            retry_after = resp.headers.get("Retry-After")
                            if retry_after:
                                try:
                                    wait_time = min(float(retry_after), 30.0)
                                except ValueError:
                                    wait_time = 0.0
                        if wait_time <= 0:
                            wait_time = (2 ** (attempt - 1)) + random.uniform(0.0, 0.5)
                        logger.warning(
                            "HTTP %d for %s; waiting %.1fs (attempt %d/%d)",
                            status,
                            url,
                            wait_time,
                            attempt,
                            retries,
                        )
                        await asyncio.sleep(wait_time)
                        continue

                    text = await resp.text()
                    raise FetchError(f"HTTP {status} Client Error at {url}: {text[:200]}")
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                attempt += 1
                if attempt > retries:
                    raise FetchError(
                        f"Network error at {url} after {retries} retries: {exc}"
                    ) from exc
                wait_time = (2 ** (attempt - 1)) + random.uniform(0.0, 0.5)
                logger.warning(
                    "Network error (%s) for %s; waiting %.1fs (attempt %d/%d)",
                    exc,
                    url,
                    wait_time,
                    attempt,
                    retries,
                )
                await asyncio.sleep(wait_time)

    if semaphore is not None:
        async with semaphore:
            return await _do_fetch()
    return await _do_fetch()
