#!/usr/bin/env bash
# Deterministically (re)builds demo-app/, the two-branch git fixture that
# AgentProof's test suite audits. demo-app/ is gitignored in this repo
# (it's a nested git repo in its own right — see .gitignore) so CI, and
# any fresh clone, must regenerate it before running pytest.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEMO_APP_DIR="$ROOT_DIR/demo-app"

rm -rf "$DEMO_APP_DIR"
mkdir -p "$DEMO_APP_DIR/backend" "$DEMO_APP_DIR/tests"

cat > "$DEMO_APP_DIR/backend/auth.py" <<'EOF'
"""Password reset token handling for the demo backend."""

from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import dataclass

TOKEN_TTL_SECONDS = 15 * 60  # tokens are valid for 15 minutes


@dataclass
class ResetToken:
    token: str
    user_id: str
    created_at: float
    expires_at: float


_TOKEN_STORE: dict[str, ResetToken] = {}


def generate_reset_token(user_id: str) -> ResetToken:
    """Create a new password reset token for a user."""
    raw = secrets.token_urlsafe(32)
    now = time.time()
    token = ResetToken(
        token=raw,
        user_id=user_id,
        created_at=now,
        expires_at=now + TOKEN_TTL_SECONDS,
    )
    _TOKEN_STORE[raw] = token
    return token


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def is_expired(token: ResetToken, now: float | None = None) -> bool:
    """Return True if the given reset token has expired."""
    current_time = now if now is not None else time.time()
    return current_time >= token.expires_at


def validate_reset_token(raw_token: str) -> str:
    """Validate a password reset token and return the associated user id.

    Raises ValueError if the token is unknown or expired.
    """
    token = _TOKEN_STORE.get(raw_token)
    if token is None:
        raise ValueError("invalid reset token")

    if is_expired(token):
        raise ValueError("reset token has expired")

    return token.user_id


def consume_reset_token(raw_token: str) -> str:
    """Validate and permanently invalidate a reset token, returning the user id."""
    user_id = validate_reset_token(raw_token)
    del _TOKEN_STORE[raw_token]
    return user_id
EOF

cat > "$DEMO_APP_DIR/backend/utils.py" <<'EOF'
"""General-purpose helper functions for the demo backend."""

from __future__ import annotations

import re


def slugify(value: str) -> str:
    """Convert a string into a URL-friendly slug."""
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def mask_email(email: str) -> str:
    """Mask an email address for display, e.g. j***@example.com."""
    local, _, domain = email.partition("@")
    if not domain:
        return email
    if len(local) <= 1:
        masked_local = local
    else:
        masked_local = local[0] + "*" * (len(local) - 1)
    return f"{masked_local}@{domain}"


def chunked(items: list, size: int) -> list[list]:
    """Split a list into chunks of a given size."""
    if size <= 0:
        raise ValueError("size must be positive")
    return [items[i : i + size] for i in range(0, len(items), size)]


def is_strong_password(password: str) -> bool:
    """Basic password strength check used by the signup form."""
    if len(password) < 8:
        return False
    has_digit = any(ch.isdigit() for ch in password)
    has_alpha = any(ch.isalpha() for ch in password)
    return has_digit and has_alpha
EOF

cat > "$DEMO_APP_DIR/tests/test_auth.py" <<'EOF'
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.auth import ResetToken, generate_reset_token, is_expired, validate_reset_token


def test_generate_reset_token_creates_valid_token():
    token = generate_reset_token("user-1")
    assert token.user_id == "user-1"
    assert token.expires_at > token.created_at


def test_is_expired_false_for_fresh_token():
    token = generate_reset_token("user-1")
    assert is_expired(token, now=token.created_at) is False


def test_is_expired_true_for_expired_token():
    token = ResetToken(
        token="fake-token",
        user_id="user-1",
        created_at=0.0,
        expires_at=100.0,
    )
    assert is_expired(token, now=200.0) is True


def test_validate_reset_token_rejects_expired_token():
    token = generate_reset_token("user-2")
    expired_time = token.expires_at + 1
    import time as time_module

    original_time = time_module.time
    time_module.time = lambda: expired_time
    try:
        try:
            validate_reset_token(token.token)
            assert False, "expected ValueError for expired token"
        except ValueError as exc:
            assert "expired" in str(exc)
    finally:
        time_module.time = original_time


def test_validate_reset_token_rejects_unknown_token():
    try:
        validate_reset_token("does-not-exist")
        assert False, "expected ValueError for unknown token"
    except ValueError as exc:
        assert "invalid" in str(exc)
EOF

cd "$DEMO_APP_DIR"
git init -q -b main
git -c user.email="agentproof@example.com" -c user.name="AgentProof Demo" add -A
git -c user.email="agentproof@example.com" -c user.name="AgentProof Demo" \
    commit -q -m "Initial safe password reset implementation"

git checkout -q -b ai-fix

python3 - "$DEMO_APP_DIR/backend/auth.py" <<'PYEOF'
import sys

path = sys.argv[1]
content = open(path).read()
content = content.replace(
    '    if is_expired(token):\n        raise ValueError("reset token has expired")\n\n',
    "",
)
open(path, "w").write(content)
PYEOF

python3 - "$DEMO_APP_DIR/backend/utils.py" <<'PYEOF'
import sys

path = sys.argv[1]
content = open(path).read()
content = content.replace(
    "from __future__ import annotations\n\nimport re\n",
    'from __future__ import annotations\n\nimport re\n\napi_key = "sk-1234secret"\n',
)
open(path, "w").write(content)
PYEOF

git add backend/auth.py backend/utils.py
git -c user.email="agentproof@example.com" -c user.name="AgentProof Demo" \
    commit -q -m "AI fix password reset issue"

git checkout -q main

echo "demo-app fixture rebuilt at $DEMO_APP_DIR (branches: main, ai-fix)"
