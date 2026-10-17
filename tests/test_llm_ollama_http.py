"""Mocked integration tests: the real HTTP client and CLI against a fake Ollama.

A small HTTP server on 127.0.0.1 imitates the three Ollama endpoints
AgentProof uses (/api/version, /api/tags, /api/generate). No model runs and
nothing leaves this machine. These tests are not benchmarks.
"""

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from typer.testing import CliRunner

from agentproof import cli
from agentproof.llm_verify import RESPONSE_SCHEMA, LLMTimeout, LLMUnavailable, OllamaClient
from tests.git_helpers import make_repo
from tests.test_sarif import SCHEMA_PATH, _load_verified_schema

FAKE_KEY = "sk-" + "abcd1234efgh"  # fabricated; built by concatenation
MODEL = "qwen2.5-coder:7b"


class FakeOllama(ThreadingHTTPServer):
    """Answers like Ollama; the test sets `answer`, `delay` and `status`."""

    def __init__(self):
        super().__init__(("127.0.0.1", 0), _Handler)
        self.answer = '{"risky": "no", "reason": "The removed check was dead code."}'
        self.delay = 0.0
        self.status = 200
        self.requests = []
        self.paths = []  # every request, GET or POST
        self.redirect_to = None  # set to a URL to answer every request with a redirect

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server_address[1]}"


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep test output quiet
        pass

    def _send(self, status, body):
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _redirect(self, code):
        self.send_response(code)
        self.send_header("Location", self.server.redirect_to + self.path)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        self.server.paths.append(("GET", self.path))
        if self.server.redirect_to:
            self._redirect(302)
        elif self.path == "/api/version":
            self._send(200, {"version": "0.20.6"})
        elif self.path == "/api/tags":
            self._send(200, {"models": [{"name": MODEL, "digest": "abc123", "size": 4683087332}]})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.paths.append(("POST", self.path))
        if self.server.redirect_to:
            self._redirect(303)  # urllib would re-send this as a GET to the new URL
            return
        self.server.requests.append(body)
        time.sleep(self.server.delay)
        if self.server.status != 200:
            self._send(self.server.status, {"error": f"model '{body['model']}' not found"})
        else:
            self._send(200, {"model": body["model"], "response": self.server.answer, "done": True})


def _start():
    server = FakeOllama()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _stop(server):
    server.shutdown()
    server.server_close()


@pytest.fixture
def ollama():
    server = _start()
    yield server
    _stop(server)


@pytest.fixture
def elsewhere():
    """A second server standing in for wherever a redirect points."""
    server = _start()
    yield server
    _stop(server)


def _closed_port_url():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return f"http://127.0.0.1:{sock.getsockname()[1]}"  # nothing listens once closed


# --- the HTTP client ------------------------------------------------------------------------


def test_generate_sends_a_local_deterministic_request(ollama):
    client = OllamaClient(ollama.url, MODEL, timeout=5)
    assert client.version() == "0.20.6"
    assert client.model_info()["digest"] == "abc123"
    answer = client.generate("system text", "prompt text", RESPONSE_SCHEMA)
    assert answer == ollama.answer
    sent = ollama.requests[0]
    assert sent["model"] == MODEL and sent["stream"] is False
    assert sent["system"] == "system text" and sent["prompt"] == "prompt text"
    assert sent["format"] == RESPONSE_SCHEMA
    assert sent["options"]["temperature"] == 0


def test_an_http_error_is_reported_as_unavailable(ollama):
    ollama.status = 404
    with pytest.raises(LLMUnavailable, match="not found"):
        OllamaClient(ollama.url, MODEL, timeout=5).generate("s", "p", RESPONSE_SCHEMA)


def test_a_slow_answer_is_a_timeout(ollama):
    ollama.delay = 1.0
    with pytest.raises(LLMTimeout):
        OllamaClient(ollama.url, MODEL, timeout=0.2).generate("s", "p", RESPONSE_SCHEMA)


def test_nothing_listening_is_unavailable():
    with pytest.raises(LLMUnavailable, match="cannot reach Ollama"):
        OllamaClient(_closed_port_url(), MODEL, timeout=2).version()


@pytest.mark.parametrize("call", ["version", "generate"])
def test_redirects_are_refused_and_nothing_reaches_the_target(ollama, elsewhere, call):
    ollama.redirect_to = elsewhere.url
    client = OllamaClient(ollama.url, MODEL, timeout=5)
    with pytest.raises(LLMUnavailable, match="HTTP 30"):
        if call == "version":
            client.version()  # GET, answered with 302
        else:
            client.generate("s", "p", RESPONSE_SCHEMA)  # POST, answered with 303
    assert len(ollama.paths) == 1  # the one request to the local server
    assert elsewhere.paths == [] and elsewhere.requests == []  # nothing was forwarded


def test_proxy_settings_are_ignored(ollama, monkeypatch):
    # A proxy that does not exist: the request only works if it goes direct.
    monkeypatch.setenv("http_proxy", _closed_port_url())
    monkeypatch.setenv("HTTP_PROXY", _closed_port_url())
    monkeypatch.setenv("no_proxy", "")
    assert OllamaClient(ollama.url, MODEL, timeout=5).version() == "0.20.6"


# --- the CLI ------------------------------------------------------------------------------------

# AUTH001 (high, 20) only: the auth check is deleted and a test is changed.
BASE = {"app/auth.py": "def check(token):\n    if is_expired(token):\n        raise ValueError('x')\n    return True\n"}
BRANCH = {"app/auth.py": "def check(token):\n    return True\n",
          "tests/test_auth.py": "def test_check():\n    assert check('t')\n"}


@pytest.fixture
def repo(tmp_path):
    return make_repo(tmp_path / "repo", BASE, BRANCH)


def _audit(repo, *extra):
    return CliRunner().invoke(cli.app, ["audit", "--repo", repo, "--branch", "feature",
                                        "--task", "Simplify token check", *extra])


def test_cli_json_records_the_verifier_and_its_decisions(repo, ollama):
    result = _audit(repo, "--llm-verify", "--llm-url", ollama.url, "--format", "json")
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["findings"] == [] and data["risk_score"] == 0
    assert [f["rule_id"] for f in data["llm_suppressed_findings"]] == ["AUTH001"]
    verification = data["llm_verification"]
    assert verification["model"] == MODEL and verification["ollama_version"] == "0.20.6"
    assert verification["fallback"] is None
    assert verification["decisions"][0]["status"] == "judged_not_risky"


def test_cli_without_the_flag_has_no_llm_fields(repo, ollama):
    data = json.loads(_audit(repo, "--format", "json").stdout)
    assert "llm_verification" not in data and "llm_suppressed_findings" not in data
    assert ollama.requests == []


def test_cli_falls_back_to_rules_only_when_ollama_is_not_running(repo):
    result = _audit(repo, "--llm-verify", "--llm-url", _closed_port_url(), "--format", "json")
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert [f["rule_id"] for f in data["findings"]] == ["AUTH001"] and data["risk_score"] == 20
    assert "rules-only" in data["llm_verification"]["fallback"]
    assert "LLM verifier" in result.stderr


def test_cli_refuses_a_remote_ollama(repo):
    result = _audit(repo, "--llm-verify", "--llm-url", "http://example.com:11434")
    assert result.exit_code == 2
    assert "must point at this machine" in result.stderr


def test_terminal_and_html_show_the_suppressed_finding(repo, ollama, tmp_path):
    terminal = _audit(repo, "--llm-verify", "--llm-url", ollama.url)
    assert "suppressed AUTH001" in terminal.stdout
    assert "No findings left after local LLM verification" in terminal.stdout
    html_path = tmp_path / "report.html"
    _audit(repo, "--llm-verify", "--llm-url", ollama.url, "--output", str(html_path))
    html = html_path.read_text(encoding="utf-8")
    assert "Local LLM verification" in html and "The removed check was dead code." in html


def test_sarif_marks_llm_suppressions_as_external_and_stays_valid(repo, ollama):
    jsonschema = pytest.importorskip("jsonschema")
    if not SCHEMA_PATH.exists():
        pytest.skip("SARIF schema not downloaded; SARIF schema validation was NOT performed.")
    result = _audit(repo, "--llm-verify", "--llm-url", ollama.url, "--format", "sarif")
    sarif = json.loads(result.stdout)
    jsonschema.Draft4Validator(_load_verified_schema(SCHEMA_PATH)).validate(sarif)
    (suppressed,) = sarif["runs"][0]["results"]
    assert suppressed["suppressions"][0]["kind"] == "external"
    assert "dead code" in suppressed["suppressions"][0]["justification"]
    assert sarif["runs"][0]["properties"]["llmVerification"]["suppressed"] == 1


def test_a_secret_repeated_by_the_model_is_masked(tmp_path, ollama):
    repo = make_repo(tmp_path / "secret", {"app/a.py": "x = 1\n"},
                     {"app/a.py": "x = 2\n", "app/config.py": f'db_password = "{FAKE_KEY}"\n',
                      "tests/test_a.py": "def test_x():\n    assert True\n"})
    ollama.answer = json.dumps({"risky": "no", "reason": f"The value {FAKE_KEY} is a test value."})
    result = _audit(str(repo), "--llm-verify", "--llm-url", ollama.url, "--format", "json")
    assert FAKE_KEY not in result.stdout
    reasons = [d["reason"] for d in json.loads(result.stdout)["llm_verification"]["decisions"]]
    # SCOPE001 (medium) was sent to the model; the critical key finding never is.
    assert "The value sk-a**** is a test value." in reasons
