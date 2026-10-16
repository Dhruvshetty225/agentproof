"""eval/github_api.py: headers, pagination, rate limits and retries (no network)."""

import io
import json
import urllib.error

import pytest

from eval.github_api import DIFF_MEDIA_TYPE, ApiError, GitHubClient

TOKEN = "test-token-not-real-0123456789"


class FakeResponse:
    def __init__(self, body: bytes, headers: dict):
        self._body = body
        self.headers = headers

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeOpener:
    """Returns queued responses in order and records every request."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append(request)
        status, headers, body = self.responses.pop(0)
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        if status >= 400:
            raise urllib.error.HTTPError(request.full_url, status, "error", headers, io.BytesIO(body))
        return FakeResponse(body, headers)


def _client(responses, clock=1000.0):
    opener = FakeOpener(responses)
    sleeps = []
    client = GitHubClient(TOKEN, opener=opener, sleep=sleeps.append, clock=lambda: clock)
    return client, opener, sleeps


def test_token_is_sent_only_in_the_authorization_header():
    client, opener, _ = _client([(200, {}, {"ok": True})])
    client.get_json("/repos/o/r", {"q": "x"})
    request = opener.requests[0]
    assert request.get_header("Authorization") == f"Bearer {TOKEN}"
    assert TOKEN not in request.full_url
    assert request.get_header("Accept") == "application/vnd.github+json"


def test_diff_requests_ask_for_the_diff_media_type():
    client, opener, _ = _client([(200, {}, b"diff --git a/x b/x\n")])
    assert client.get_text("/repos/o/r/compare/a...b").startswith("diff --git")
    assert opener.requests[0].get_header("Accept") == DIFF_MEDIA_TYPE


def test_pagination_follows_next_links_until_the_last_page():
    page2 = "https://api.github.com/search/issues?page=2"
    client, opener, _ = _client([
        (200, {"link": f'<{page2}>; rel="next", <{page2}>; rel="last"'}, {"items": [1, 2]}),
        (200, {}, {"items": [3]}),
    ])
    assert list(client.paginate("/search/issues", {"q": "x"})) == [1, 2, 3]
    assert opener.requests[1].full_url == page2


def test_pagination_stops_at_max_pages():
    nxt = {"Link": '<https://api.github.com/x?page=2>; rel="next"'}
    client, opener, _ = _client([(200, nxt, {"items": [1]}), (200, nxt, {"items": [2]})])
    assert list(client.paginate("/x", max_pages=1)) == [1]
    assert len(opener.requests) == 1


def test_primary_rate_limit_waits_until_reset_then_retries():
    limited = {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1030"}
    client, _, sleeps = _client([(403, limited, {"message": "rate limit"}), (200, {}, {"ok": 1})], clock=1000.0)
    assert client.get_json("/x") == {"ok": 1}
    assert sleeps == [31.0]
    assert client.rate_limit_waits == 1


def test_secondary_rate_limit_uses_retry_after():
    client, _, sleeps = _client([(429, {"Retry-After": "7"}, {}), (200, {}, {"ok": 1})])
    assert client.get_json("/x") == {"ok": 1}
    assert sleeps == [7.0]


def test_server_errors_are_retried_with_backoff():
    client, _, sleeps = _client([(502, {}, {}), (503, {}, {}), (200, {}, {"ok": 1})])
    assert client.get_json("/x") == {"ok": 1}
    assert sleeps == [1, 2]


def test_server_errors_give_up_after_max_retries():
    client, _, sleeps = _client([(502, {}, {})] * 6)
    with pytest.raises(ApiError) as error:
        client.get_json("/x")
    assert error.value.status == 502
    assert sleeps == [1, 2, 4, 8, 16]


def test_client_errors_are_not_retried_and_never_mention_the_token():
    client, _, sleeps = _client([(404, {}, {"message": "Not Found"})])
    with pytest.raises(ApiError) as error:
        client.get_json("/repos/o/missing")
    assert error.value.status == 404
    assert "Not Found" in str(error.value)
    assert TOKEN not in str(error.value)
    assert sleeps == []


def test_403_without_rate_limit_headers_is_an_error_not_a_wait():
    client, _, sleeps = _client([(403, {"x-ratelimit-remaining": "42"}, {"message": "Forbidden"})])
    with pytest.raises(ApiError):
        client.get_json("/x")
    assert sleeps == []


def test_network_errors_are_retried():
    calls = {"count": 0}

    def flaky_opener(request, timeout):
        calls["count"] += 1
        if calls["count"] < 3:
            raise urllib.error.URLError("connection reset")
        return FakeResponse(b'{"ok": 1}', {})

    sleeps = []
    client = GitHubClient(TOKEN, opener=flaky_opener, sleep=sleeps.append)
    assert client.get_json("/x") == {"ok": 1}
    assert sleeps == [1, 2]
