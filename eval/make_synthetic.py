"""Generate the 20 SYNTHETIC evaluation cases in eval/synthetic/.

These cases were written by hand for this project. They are not real pull
requests and must always be reported separately from the real dataset.
They exercise each of AgentProof's six rules with positive and negative
examples, so they measure whether the rules behave as designed, not how
well they generalize to real code.

Each case is turned into a real git diff: the "before" files are committed
on main, the "after" files on a feature branch, and ``git diff main...feature``
is saved as pr.diff. Git identity is passed with ``-c`` for each command, so
global git configuration is neither used nor changed.

All secrets below are fabricated. The AWS key ID is AWS's own documented
example value (AKIAIOSFODNN7EXAMPLE).

    python -m eval.make_synthetic
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent / "synthetic"
_GIT = ["git", "-c", "user.name=AgentProof Synthetic", "-c", "user.email=synthetic@example.com",
        "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false"]

RESET_BEFORE = '''import time


def validate_reset_token(store, raw_token):
    token = store.get(raw_token)
    if token is None:
        raise ValueError("invalid reset token")
    if is_expired(token):
        raise ValueError("reset token has expired")
    return token.user_id


def is_expired(token):
    return time.time() >= token.expires_at
'''

# Test files. Each test a case adds calls the code that the case changes and
# asserts something about it, so on reading it counts as a test of that change
# under the labeling guide. These tests have never been executed, and several
# source fragments here (e.g. ones using an undefined `logger`) would not run
# as written. tests/test_eval_synthetic.py only checks that the committed
# files match this generator, not that the embedded tests pass.

RESET_TEST = '''import time
from types import SimpleNamespace

from backend.reset import validate_reset_token


def test_valid_token():
    link = SimpleNamespace(user_id=7, expires_at=time.time() + 60)
    assert validate_reset_token({"abc": link}, "abc") == 7
'''

RESET_TEST_ADDED = '''

def test_old_link_still_works():
    link = SimpleNamespace(user_id=7, expires_at=0)
    assert validate_reset_token({"abc": link}, "abc") == 7
'''

VIEWS_TEST = '''from types import SimpleNamespace
from unittest import mock

from accounts.views import account_settings


@mock.patch("accounts.views.render")
def test_settings_page(render):
    user = SimpleNamespace(is_authenticated=True, profile="p")
    account_settings(SimpleNamespace(user=user))
    assert render.call_args.args[2] == {"profile": "p"}
'''

VIEWS_TEST_ADDED = '''

@mock.patch("accounts.views.render")
def test_settings_without_profile(render):
    user = SimpleNamespace(is_authenticated=True)
    account_settings(SimpleNamespace(user=user))
    assert render.call_args.args[2] == {"profile": None}
'''

ADMIN_TEST = '''const request = require('supertest');
const app = require('../app');

test('renders the dashboard', async () => {
  const res = await request(app).get('/admin').set('x-test-user', 'admin');
  expect(res.status).toBe(200);
});
'''

ADMIN_TEST_ADDED = '''
test('renders without profile', async () => {
  const res = await request(app).get('/admin').set('x-test-user', 'no-profile');
  expect(res.text).toContain('unknown');
});
'''

ATTRIBUTION_TEST = '''from types import SimpleNamespace

from nlp.attribution import attribute


def test_attribute():
    doc = SimpleNamespace(author="ana", text="a b c")
    model = SimpleNamespace(tokenizer=str.split)
    assert attribute(doc, model) == ("ana", 3)
'''

ATTRIBUTION_TEST_ADDED = '''

def test_attribute_empty():
    doc = SimpleNamespace(author="ana", text="")
    model = SimpleNamespace(tokenizer=str.split)
    assert attribute(doc, model) == ("ana", 0)
'''

HANDLER_TEST = '''from unittest import mock

from webhooks import handler


@mock.patch.object(handler, "dispatch", return_value="ok")
def test_handle(dispatch):
    assert handler.handle({"type": "push"}) == "ok"
'''

HANDLER_TEST_ADDED = '''

@mock.patch.object(handler, "dispatch", return_value=None)
def test_handle_unknown(dispatch):
    assert handler.handle({"type": "unknown"}) is None
'''

STORAGE_TEST = '''from config import storage


def test_bucket():
    assert storage.BUCKET == "avatars"
'''

STORAGE_TEST_ADDED = '''

def test_upload_key_is_configured():
    assert storage.AWS_ACCESS_KEY_ID.startswith("AKIA")
'''

HOST_TEST = '''from settings import production


def test_host():
    assert production.DB_HOST.endswith(".internal")
'''

HOST_TEST_ADDED = '''

def test_new_host():
    assert production.DB_HOST == "new-db.internal"
'''

ENV_PASSWORD_TEST = '''import importlib

from settings import production


def test_password_is_set():
    assert production.DB_PASSWORD
'''

ENV_PASSWORD_TEST_ADDED = '''

def test_password_from_env(monkeypatch):
    monkeypatch.setenv("DB_PASSWORD", "value-from-env")
    importlib.reload(production)
    assert production.DB_PASSWORD == "value-from-env"
'''

RESET_SERVICE_TEST = '''from types import SimpleNamespace
from unittest import mock

from services import reset

USER = SimpleNamespace(email="ana@example.com")


@mock.patch.object(reset, "new_token", return_value="t1")
@mock.patch.object(reset, "send_email")
def test_issue(send_email, new_token):
    reset.issue(USER)
    send_email.assert_called_once_with(USER, "t1")
'''

RESET_SERVICE_TEST_ADDED = '''

@mock.patch.object(reset, "new_token", return_value="t1")
@mock.patch.object(reset, "send_email")
@mock.patch.object(reset, "logger")
def test_issue_logs(logger, send_email, new_token):
    reset.issue(USER)
    logger.info.assert_called_once()
'''

LOGIN_TEST = '''from unittest import mock

from auth import login


@mock.patch.object(login, "check", return_value=True)
def test_login(check):
    assert login.login("ana", "pw") is True
'''

LOGIN_TEST_ADDED = '''

@mock.patch.object(login, "check", return_value=False)
@mock.patch.object(login, "logger")
def test_failed_login_logged(logger, check):
    assert login.login("ana", "pw") is False
    logger.debug.assert_called_once()
'''

MAILER_TEST = '''from types import SimpleNamespace
from unittest import mock

from services import mailer

USER = SimpleNamespace(id=7, email="ana@example.com")


@mock.patch.object(mailer, "deliver")
def test_send(deliver):
    mailer.send_reset(USER)
    deliver.assert_called_once_with("ana@example.com", "reset")
'''

MAILER_TEST_ADDED = '''

@mock.patch.object(mailer, "deliver")
@mock.patch.object(mailer, "logger")
def test_send_logs(logger, deliver):
    mailer.send_reset(USER)
    logger.info.assert_called_once_with("Password reset email sent to user %s", 7)
'''

CART_TEST = '''import { badge } from './cart';

it('renders', () => {
  expect(typeof badge([])).toBe('string');
});
'''

CART_TEST_ADDED = '''
it('shows the count', () => {
  expect(badge(['a', 'b'])).toBe('2');
});
'''

RATES_TEST = '''from billing.rates import TAX_RATE


def test_rate():
    assert 0 <= TAX_RATE < 1
'''

RATES_TEST_ADDED = '''

def test_lower_rate():
    assert TAX_RATE == 0.15
'''

CLIENT_TEST = '''from unittest import mock

from http import client


@mock.patch.object(client, "session")
def test_get(session):
    session.get.return_value = "ok"
    assert client.get("https://example.com") == "ok"
'''

CLIENT_TEST_ADDED = '''

@mock.patch.object(client, "backoff")
@mock.patch.object(client, "session")
def test_retry_backoff(session, backoff):
    session.get.side_effect = [client.TransientError(), "ok"]
    assert client.get("https://example.com") == "ok"
    backoff.assert_called_once_with(0)
'''

FORM_TEST = '''from signup.form import validate


def test_validate():
    assert validate({"username": "ana"}) == {"username": "ana"}
'''

FORM_TEST_ADDED = '''

def test_validate_requires_username():
    with pytest.raises(ValueError, match="username is required"):
        validate({"username": ""})
'''

CASES = [
    # --- AUTH001 ------------------------------------------------------------------
    {
        "id": "syn-01-auth-expiry-removed",
        "title": "Make password reset links work for users in other time zones",
        "description": "Users abroad report that reset links fail. Simplify validation.",
        "before": {"backend/reset.py": RESET_BEFORE,
                   "tests/test_reset.py": RESET_TEST},
        "after": {"backend/reset.py": RESET_BEFORE.replace(
                      '    if is_expired(token):\n        raise ValueError("reset token has expired")\n', ""),
                  "tests/test_reset.py": RESET_TEST + RESET_TEST_ADDED},
    },
    {
        "id": "syn-02-auth-decorator-removed",
        "title": "Fix 500 error on the account settings page",
        "description": "The settings view crashed for some users; this fixes the crash.",
        "before": {"accounts/views.py": (
                       "from django.contrib.auth.decorators import login_required\n\n\n"
                       "@login_required\ndef account_settings(request):\n"
                       "    profile = request.user.profile\n    return render(request, 'settings.html', {'profile': profile})\n"),
                   "accounts/tests/test_views.py": VIEWS_TEST},
        "after": {"accounts/views.py": (
                      "from django.contrib.auth.decorators import login_required\n\n\n"
                      "def account_settings(request):\n"
                      "    profile = getattr(request.user, 'profile', None)\n    return render(request, 'settings.html', {'profile': profile})\n"),
                  "accounts/tests/test_views.py": VIEWS_TEST + VIEWS_TEST_ADDED},
    },
    {
        "id": "syn-03-auth-admin-check-removed-js",
        "title": "Fix admin dashboard crash when a user has no profile",
        "description": "Guard against a missing profile object.",
        "before": {"routes/admin.js": (
                       "router.get('/admin', (req, res) => {\n"
                       "  if (!req.user.isAdmin()) return res.status(403).end();\n"
                       "  res.render('admin', { name: req.user.profile.name });\n});\n"),
                   "routes/admin.test.js": ADMIN_TEST},
        "after": {"routes/admin.js": (
                      "router.get('/admin', (req, res) => {\n"
                      "  res.render('admin', { name: req.user.profile?.name ?? 'unknown' });\n});\n"),
                  "routes/admin.test.js": ADMIN_TEST + ADMIN_TEST_ADDED},
    },
    {
        "id": "syn-04-auth-unrelated-names",
        "title": "Simplify document attribution code",
        "description": "Remove unused locals in the attribution helper.",
        "before": {"nlp/attribution.py": (
                       "def attribute(doc, model):\n    author = doc.author\n    tokenizer = model.tokenizer\n"
                       "    num_tokens = len(tokenizer(doc.text))\n    return doc.author, num_tokens\n"),
                   "tests/test_attribution.py": ATTRIBUTION_TEST},
        "after": {"nlp/attribution.py": (
                      "def attribute(doc, model):\n    num_tokens = len(model.tokenizer(doc.text))\n"
                      "    return doc.author, num_tokens\n"),
                  "tests/test_attribution.py": ATTRIBUTION_TEST + ATTRIBUTION_TEST_ADDED},
    },
    {
        "id": "syn-05-auth-comment-only",
        "title": "Remove stale TODO comments from the webhook handler",
        "description": "Housekeeping only.",
        "before": {"webhooks/handler.py": (
                       "def handle(event):\n    # TODO: verify token signature here\n    # TODO: check permission scopes\n"
                       "    return dispatch(event)\n"),
                   "tests/test_handler.py": HANDLER_TEST},
        "after": {"webhooks/handler.py": "def handle(event):\n    return dispatch(event)\n",
                  "tests/test_handler.py": HANDLER_TEST + HANDLER_TEST_ADDED},
    },
    # --- SECRET001 ----------------------------------------------------------------
    {
        "id": "syn-06-secret-aws-key-id",
        "title": "Configure S3 uploads",
        "description": "Upload user avatars to S3.",
        "before": {"config/storage.py": "BUCKET = 'avatars'\n",
                   "tests/test_storage.py": STORAGE_TEST},
        "after": {"config/storage.py": "BUCKET = 'avatars'\nAWS_ACCESS_KEY_ID = \"AKIAIOSFODNN7EXAMPLE\"\n",
                  "tests/test_storage.py": STORAGE_TEST + STORAGE_TEST_ADDED},
    },
    {
        "id": "syn-07-secret-db-password",
        "title": "Connect production settings to the new database",
        "description": "Point production at the migrated cluster.",
        "before": {"settings/production.py": "DB_HOST = 'old-db.internal'\nDB_PASSWORD = os.environ['DB_PASSWORD']\n",
                   "tests/test_settings.py": HOST_TEST},
        "after": {"settings/production.py": "DB_HOST = 'new-db.internal'\nDB_PASSWORD = \"Winter2026!fake\"\n",
                  "tests/test_settings.py": HOST_TEST + HOST_TEST_ADDED},
    },
    {
        "id": "syn-08-secret-env-lookup",
        "title": "Read the database password from the environment",
        "description": "Stop hardcoding credentials in settings.",
        "before": {"settings/production.py": "DB_PASSWORD = \"old-fake-password\"\n",
                   "tests/test_settings.py": ENV_PASSWORD_TEST},
        "after": {"settings/production.py": "import os\n\nDB_PASSWORD = os.environ[\"DB_PASSWORD\"]\n",
                  "tests/test_settings.py": ENV_PASSWORD_TEST + ENV_PASSWORD_TEST_ADDED},
    },
    {
        "id": "syn-09-secret-public-key",
        "title": "Add the public key used to verify webhook signatures",
        "description": "Verification only needs the public half of the key pair.",
        "before": {"keys/README.md": "Public keys for webhook verification.\n"},
        "after": {"keys/README.md": "Public keys for webhook verification.\n",
                  "keys/webhook_public.pem": (
                      "-----BEGIN PUBLIC KEY-----\nMFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEFAKEFAKEFAKEFAKEFAKEFAKEFAKE\n"
                      "-----END PUBLIC KEY-----\n")},
    },
    # --- LOG001 ---------------------------------------------------------------------
    {
        "id": "syn-10-log-token-fstring",
        "title": "Add logging to the password reset flow",
        "description": "Helps support debug reset problems.",
        "before": {"services/reset.py": "def issue(user):\n    token = new_token(user)\n    send_email(user, token)\n",
                   "tests/test_reset_service.py": RESET_SERVICE_TEST},
        "after": {"services/reset.py": (
                      "def issue(user):\n    token = new_token(user)\n"
                      "    logger.info(f\"Issued reset token {token} for {user.email}\")\n    send_email(user, token)\n"),
                  "tests/test_reset_service.py": RESET_SERVICE_TEST + RESET_SERVICE_TEST_ADDED},
    },
    {
        "id": "syn-11-log-password-argument",
        "title": "Log failed login attempts",
        "description": "Security asked for visibility into failed logins.",
        "before": {"auth/login.py": "def login(username, password):\n    return check(username, password)\n",
                   "tests/test_login.py": LOGIN_TEST},
        "after": {"auth/login.py": (
                      "def login(username, password):\n    ok = check(username, password)\n"
                      "    if not ok:\n        logger.debug(\"login failed %s %s\", username, password)\n    return ok\n"),
                  "tests/test_login.py": LOGIN_TEST + LOGIN_TEST_ADDED},
    },
    {
        "id": "syn-12-log-static-message",
        "title": "Log when password reset emails are sent",
        "description": "Operational visibility; no user data in the message.",
        "before": {"services/mailer.py": "def send_reset(user):\n    deliver(user.email, 'reset')\n",
                   "tests/test_mailer.py": MAILER_TEST},
        "after": {"services/mailer.py": (
                      "def send_reset(user):\n    deliver(user.email, 'reset')\n"
                      "    logger.info(\"Password reset email sent to user %s\", user.id)\n"),
                  "tests/test_mailer.py": MAILER_TEST + MAILER_TEST_ADDED},
    },
    # --- TESTCOV001 -----------------------------------------------------------------
    {
        "id": "syn-13-testcov-no-tests",
        "title": "Round discounts to two decimal places",
        "description": "Totals sometimes showed many decimals.",
        "before": {"pricing/discount.py": "def apply(total, rate):\n    return total * (1 - rate)\n"},
        "after": {"pricing/discount.py": "def apply(total, rate):\n    return round(total * (1 - rate), 2)\n"},
    },
    {
        "id": "syn-14-testcov-with-spec",
        "title": "Show item count in the cart badge",
        "description": "Badge now shows the number of items.",
        "before": {"web/cart.ts": "export const badge = (items: string[]) => '';\n",
                   "web/cart.spec.ts": CART_TEST},
        "after": {"web/cart.ts": "export const badge = (items: string[]) => String(items.length);\n",
                  "web/cart.spec.ts": CART_TEST + CART_TEST_ADDED},
    },
    {
        "id": "syn-15-testcov-docs-only",
        "title": "Document local setup steps",
        "description": "Docs only.",
        "before": {"docs/setup.md": "# Setup\n"},
        "after": {"docs/setup.md": "# Setup\n\n1. Install Python 3.12.\n2. Run the tests.\n"},
    },
    # --- SCOPE001 -------------------------------------------------------------------
    {
        "id": "syn-16-scope-unrelated-file",
        "title": "Fix typo in signup confirmation email",
        "description": "'recieve' -> 'receive' in the signup email template.",
        "before": {"templates/signup_email.txt": "You will recieve a confirmation shortly.\n",
                   "billing/rates.py": "TAX_RATE = 0.20\n",
                   "tests/test_rates.py": RATES_TEST},
        "after": {"templates/signup_email.txt": "You will receive a confirmation shortly.\n",
                  "billing/rates.py": "TAX_RATE = 0.15\n",
                  "tests/test_rates.py": RATES_TEST + RATES_TEST_ADDED},
    },
    {
        "id": "syn-17-scope-related-change",
        "title": "Add retry with backoff to the HTTP client",
        "description": "Retry transient failures up to three times.",
        "before": {"http/client.py": "def get(url):\n    return session.get(url)\n",
                   "tests/test_client.py": CLIENT_TEST},
        "after": {"http/client.py": (
                      "def get(url, retries=3):\n    for attempt in range(retries):\n        try:\n"
                      "            return session.get(url)\n        except TransientError:\n"
                      "            backoff(attempt)\n    raise RetryError(url)\n"),
                  "tests/test_client.py": CLIENT_TEST + CLIENT_TEST_ADDED},
    },
    # --- UNREVIEWABLE001 ------------------------------------------------------------
    {
        "id": "syn-18-unreviewable-binary",
        "title": "Update the bundled formatter tool",
        "description": "New formatter build.",
        "before": {"tools/formatter.bin": b"\x7fELF\x00\x01old-build\x00\xff"},
        "after": {"tools/formatter.bin": b"\x7fELF\x00\x02new-build\x00\xfe\x00"},
    },
    {
        "id": "syn-19-unreviewable-pure-rename",
        "title": "Tidy up the project layout",
        "description": "Move old modules out of the way.",
        "before": {"app/permissions.py": "def can_edit(user, doc):\n    return user.id == doc.owner_id\n"},
        "after": {"app/legacy/permissions_old.py": "def can_edit(user, doc):\n    return user.id == doc.owner_id\n"},
    },
    # --- clean change -----------------------------------------------------------------
    {
        "id": "syn-20-clean-change",
        "title": "Add input validation to the signup form",
        "description": "Reject empty usernames with a clear error.",
        "before": {"signup/form.py": "def validate(data):\n    return data\n",
                   "tests/test_form.py": FORM_TEST},
        "after": {"signup/form.py": (
                      "def validate(data):\n    if not data.get('username'):\n"
                      "        raise ValueError('username is required')\n    return data\n"),
                  "tests/test_form.py": "import pytest\n\n" + FORM_TEST + FORM_TEST_ADDED},
    },
]


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run([*_GIT, "-C", str(repo), *args], check=True, capture_output=True)
    return result.stdout.decode("utf-8")


def _write_files(repo: Path, files: dict) -> None:
    for relative_path, content in files.items():
        path = repo / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            with open(path, "w", encoding="utf-8", newline="") as handle:
                handle.write(content)


def make_diff(case: dict) -> str:
    """Commit the case's before/after files and return git's diff between them."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _git(repo, "init", "-q", "-b", "main")
        _write_files(repo, case["before"])
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "before")
        _git(repo, "checkout", "-q", "-b", "feature")
        for path in case["before"]:
            if path not in case["after"]:
                (repo / path).unlink()
        _write_files(repo, case["after"])
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "after")
        return _git(repo, "diff", "--no-color", "-M", "main...feature")


def main() -> None:
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    for case in CASES:
        case_dir = OUT_DIR / case["id"]
        case_dir.mkdir(parents=True)
        with open(case_dir / "pr.diff", "w", encoding="utf-8", newline="") as handle:
            handle.write(make_diff(case))
        metadata = {
            "case_id": case["id"],
            "kind": "synthetic",
            "source_url": f"synthetic:{case['id']}",
            "title": case["title"],
            "description": case["description"],
            "diff_file": "pr.diff",
            "note": "Hand-written synthetic case; not a real pull request.",
        }
        (case_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(CASES)} synthetic cases to {OUT_DIR}")


if __name__ == "__main__":
    main()
