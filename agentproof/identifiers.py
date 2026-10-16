"""Split source-code identifiers into lowercase words for whole-word matching.

Rules use these helpers instead of raw substring searches, so that
"is_authorized" and "isAuthorized" both contain the word "authorized" while
"author" does not contain the word "auth".
"""

from __future__ import annotations

import re

_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_SEPARATOR_RE = re.compile(r"[_\-]+")
# Zero-width split points inside a camelCase or PascalCase name:
#   "isAuthorized" -> "is" | "Authorized"  (lowercase or digit, then uppercase)
#   "CSRFToken"    -> "CSRF" | "Token"     (an acronym, then a capitalized word)
_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def identifiers_in(text: str) -> list[str]:
    """Return every identifier-like name in `text`, in order of appearance."""
    return _IDENTIFIER_RE.findall(text)


def identifier_words(identifier: str) -> list[str]:
    """Split a snake_case, kebab-case, camelCase or PascalCase name into words.

    identifier_words("check_permission") -> ["check", "permission"]
    identifier_words("isAuthorized")     -> ["is", "authorized"]
    identifier_words("CSRFToken")        -> ["csrf", "token"]
    """
    words: list[str] = []
    for part in _SEPARATOR_RE.split(identifier):
        words.extend(word.lower() for word in _CAMEL_BOUNDARY_RE.split(part) if word)
    return words


def contains_phrase(words: list[str], phrase: tuple[str, ...]) -> bool:
    """True if `phrase` appears as consecutive entries of `words`."""
    size = len(phrase)
    return any(tuple(words[i : i + size]) == phrase for i in range(len(words) - size + 1))


def ends_with_phrase(words: list[str], phrase: tuple[str, ...]) -> bool:
    """True if the last entries of `words` are exactly `phrase`."""
    return len(words) >= len(phrase) and tuple(words[-len(phrase) :]) == phrase
