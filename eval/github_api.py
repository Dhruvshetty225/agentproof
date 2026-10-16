"""A small read-only GitHub REST API client (standard library only).

* The token is sent only in the Authorization header. It never appears in
  URLs, error messages, logs or saved files.
* Rate limits: when GitHub answers 403/429 with ``X-RateLimit-Remaining: 0``
  the client sleeps until ``X-RateLimit-Reset``; with ``Retry-After`` (the
  secondary rate limit) it sleeps that many seconds. Then it retries.
* Server errors (5xx) and network errors are retried with exponential
  backoff. Other client errors (404, 406, 422, ...) raise ApiError at once.
* Pagination follows the ``Link: <...>; rel="next"`` header.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Iterator, Optional

API_ROOT = "https://api.github.com"
JSON_MEDIA_TYPE = "application/vnd.github+json"
DIFF_MEDIA_TYPE = "application/vnd.github.diff"
_NEXT_LINK_RE = re.compile(r'<([^>]+)>;\s*rel="next"')


class ApiError(Exception):
    """A GitHub API request failed. The message never contains the token."""

    def __init__(self, status: int, url: str, detail: str):
        super().__init__(f"GitHub API {status} for {url}: {detail}")
        self.status = status


class GitHubClient:
    def __init__(
        self,
        token: str,
        opener: Callable = urllib.request.urlopen,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
        max_retries: int = 5,
        log: Callable[[str], None] = lambda message: None,
    ):
        self._token = token
        self._opener = opener
        self._sleep = sleep
        self._clock = clock
        self._max_retries = max_retries
        self._log = log
        self.rate_limit_waits = 0

    # --- public helpers ---------------------------------------------------------

    def get_json(self, path: str, params: Optional[dict] = None):
        body, _headers = self._request(self._url(path, params), JSON_MEDIA_TYPE)
        return json.loads(body.decode("utf-8"))

    def get_text(self, path: str, media_type: str = DIFF_MEDIA_TYPE) -> str:
        body, _headers = self._request(self._url(path), media_type)
        return body.decode("utf-8", errors="replace")

    def paginate(self, path: str, params: Optional[dict] = None, max_pages: int = 10) -> Iterator[dict]:
        """Yield items page by page. Search responses keep their items under "items"."""
        url = self._url(path, params)
        for _page in range(max_pages):
            body, headers = self._request(url, JSON_MEDIA_TYPE)
            data = json.loads(body.decode("utf-8"))
            yield from data["items"] if isinstance(data, dict) else data
            match = _NEXT_LINK_RE.search(headers.get("link", ""))
            if not match:
                return
            url = match.group(1)

    # --- internals --------------------------------------------------------------------

    @staticmethod
    def _url(path: str, params: Optional[dict] = None) -> str:
        url = path if path.startswith("https://") else API_ROOT + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        return url

    def _request(self, url: str, media_type: str) -> tuple[bytes, dict]:
        request = urllib.request.Request(
            url,
            headers={
                "Accept": media_type,
                "Authorization": f"Bearer {self._token}",
                "User-Agent": "agentproof-eval-collector",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        for attempt in range(self._max_retries + 1):
            try:
                with self._opener(request, timeout=60) as response:
                    return response.read(), _lowercase_keys(response.headers)
            except urllib.error.HTTPError as error:
                headers = _lowercase_keys(error.headers or {})
                wait = self._rate_limit_wait(error.code, headers)
                if wait is not None and attempt < self._max_retries:
                    self.rate_limit_waits += 1
                    self._log(f"rate limited; waiting {wait:.0f}s")
                    self._sleep(wait)
                    continue
                if error.code >= 500 and attempt < self._max_retries:
                    self._sleep(2**attempt)
                    continue
                raise ApiError(error.code, url, _error_detail(error)) from None
            except urllib.error.URLError as error:
                if attempt < self._max_retries:
                    self._sleep(2**attempt)
                    continue
                raise ApiError(0, url, f"network error: {error.reason}") from None
        raise ApiError(0, url, "retries exhausted")  # not reached; keeps type checkers happy

    def _rate_limit_wait(self, status: int, headers: dict) -> Optional[float]:
        if status not in (403, 429):
            return None
        if headers.get("retry-after"):
            return float(headers["retry-after"])
        if headers.get("x-ratelimit-remaining") == "0" and headers.get("x-ratelimit-reset"):
            return max(float(headers["x-ratelimit-reset"]) - self._clock(), 0) + 1
        return None


def _lowercase_keys(headers) -> dict:
    """HTTP header names are case-insensitive; GitHub may send them in lowercase."""
    return {name.lower(): value for name, value in headers.items()}


def _error_detail(error: urllib.error.HTTPError) -> str:
    try:
        return json.loads(error.read().decode("utf-8")).get("message", error.reason)
    except (ValueError, AttributeError):
        return str(error.reason)
