"""Detect unsafe logging or printing of sensitive values.

Only the *values* passed to a log call matter. Words inside a static message,
as in ``logger.info("Reset token sent")``, describe an event; they do not put
a secret into the log, so they are ignored.

Quoted text is not ignored blindly. These still count as logged values:
f-string ``{...}`` and JavaScript template ``${...}`` placeholders, and quoted
lookup keys such as ``data["password"]``, ``data.get("token")``,
``os.getenv("API_TOKEN")`` and ``{"password": value}``. Plain arguments,
``"..." + value`` concatenation, ``.format(value)`` and ``% value`` are code,
so they count as well.

A name is sensitive when it *ends* with a sensitive word: "access_token" and
"system_prompt" count, but "token_count" and "prompt_tokens" do not.
"""

from __future__ import annotations

import re

from agentproof.diff_parser import FileDiff
from agentproof.identifiers import ends_with_phrase, identifier_words, identifiers_in
from agentproof.schema import Finding, Severity

RULE_ID = "LOG001"

_LOG_CALL_RE = re.compile(r"(?i)\b(print|log(?:ging|ger)?\.\w+)\s*\(")

_HIGH_RISK_SUFFIXES = [("password",), ("token",), ("secret",), ("api", "key"), ("apikey",)]
_MEDIUM_RISK_SUFFIXES = [("prompt",), ("user", "message")]

_QUOTES = ("'", '"', "`")
_F_STRING_PREFIXES = {"f", "rf", "fr"}
_LOOKUP_OPENERS = ("[", ".get(", "getenv(")


# --- separating logged values from static message text ----------------------


def _string_end(text: str, start: int) -> int:
    """Index of the quote closing the string opened at `start` (or len(text))."""
    quote = text[start]
    i = start + 1
    while i < len(text):
        if text[i] == "\\":
            i += 2
        elif text[i] == quote:
            return i
        else:
            i += 1
    return len(text)


def _matching_brace(text: str, start: int) -> int:
    """Index of the "}" closing a placeholder whose body starts at `start`."""
    depth = 1
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return i
    return len(text)


def _placeholders(literal: str, opener: str) -> list[str]:
    """Expressions inside f-string ``{...}`` or template ``${...}`` placeholders."""
    expressions = []
    i = 0
    while i < len(literal):
        if literal.startswith("{{", i):  # an escaped, literal brace
            i += 2
        elif literal.startswith(opener, i):
            body_start = i + len(opener)
            body_end = _matching_brace(literal, body_start)
            expressions.append(literal[body_start:body_end])
            i = body_end + 1
        else:
            i += 1
    return expressions


def _string_prefix(text: str, quote_index: int) -> str:
    """Letters directly before a quote, e.g. "f" in f"..." or "rb" in rb"..."."""
    start = quote_index
    while start > 0 and text[start - 1].isalpha():
        start -= 1
    return text[start:quote_index].lower()


def _is_lookup_key(text: str, start: int, end: int) -> bool:
    """True for strings used as keys: x["k"], x.get("k"), getenv("k"), {"k": v}."""
    before = text[:start].rstrip()
    after = text[end + 1 :].lstrip()
    return before.endswith(_LOOKUP_OPENERS) or after.startswith(":")


def _logged_code(text: str) -> str:
    """Return `text` with static string content removed.

    Code outside strings is kept as-is. From each string literal, only the
    parts that carry a value are kept (see the module docstring).
    """
    pieces = []
    i = 0
    while i < len(text):
        if text[i] not in _QUOTES:
            pieces.append(text[i])
            i += 1
            continue

        end = _string_end(text, i)
        literal = text[i + 1 : end]
        if _is_lookup_key(text, i, end):
            pieces.append(f" {literal} ")
        elif text[i] == "`":
            pieces.extend(f" {expr} " for expr in _placeholders(literal, "${"))
        elif _string_prefix(text, i) in _F_STRING_PREFIXES:
            pieces.extend(f" {expr} " for expr in _placeholders(literal, "{"))
        i = end + 1
    return "".join(pieces)


# --- deciding whether a logged name is sensitive -----------------------------


def _severity_of(name: str) -> Severity | None:
    words = identifier_words(name)
    if any(ends_with_phrase(words, suffix) for suffix in _HIGH_RISK_SUFFIXES):
        return Severity.HIGH
    if any(ends_with_phrase(words, suffix) for suffix in _MEDIUM_RISK_SUFFIXES):
        return Severity.MEDIUM
    return None


def _most_sensitive_name(code: str) -> tuple[str, Severity] | None:
    """The first high-risk name in `code`, else the first medium-risk name."""
    medium = None
    for name in identifiers_in(code):
        severity = _severity_of(name)
        if severity == Severity.HIGH:
            return name, severity
        if severity == Severity.MEDIUM and medium is None:
            medium = (name, severity)
    return medium


def check(file_diffs: list[FileDiff], task: str | None = None) -> list[Finding]:
    findings: list[Finding] = []
    for file_diff in file_diffs:
        for line in file_diff.added_lines:
            content = line.content
            call = _LOG_CALL_RE.search(content)
            if not call:
                continue

            # Only the call's arguments matter, not code before the call.
            sensitive = _most_sensitive_name(_logged_code(content[call.end() :]))
            if sensitive is None:
                continue

            name, severity = sensitive
            findings.append(
                Finding(
                    rule_id=RULE_ID,
                    severity=severity,
                    title="Sensitive value may be logged or printed",
                    file_path=file_diff.file_path,
                    line_number=line.line_number,
                    evidence=content.strip(),
                    recommendation=(
                        f"Avoid logging or printing '{name}' directly. Redact or "
                        "omit sensitive fields before writing to logs or stdout."
                    ),
                )
            )
    return findings
