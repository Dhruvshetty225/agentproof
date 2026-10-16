"""Hide secrets in report output. Every renderer calls redact_report() first.

Policy:

* A secret longer than four characters keeps its first four characters,
  followed by "****" ("sk-1234secret" -> "sk-1****"). Four characters or
  fewer are fully masked as "****".
* A PEM private key keeps its BEGIN/END header lines, but the key body
  between them is always replaced by "****", never partially shown.
* Secrets are collected from *every* finding first and then masked in every
  finding. A value that SECRET001 found on one line is therefore also hidden
  when the same value appears in another rule's evidence.

Only values that SECRET001's detection recognizes can be masked; see
rules/secrets.py for what that covers.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Iterable

from agentproof.rules.secrets import secret_values
from agentproof.schema import AuditReport, Finding

MASK = "****"
_VISIBLE_PREFIX = 4

# Broader than SECRET001's header check on purpose (any key type, PGP blocks):
# masking too much is safer than showing a key body.
_PRIVATE_KEY_RE = re.compile(
    r"(-----BEGIN [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----)"
    r"(.*?)"
    r"(-----END [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----|$)",
    re.DOTALL,
)


def mask_secret(secret: str) -> str:
    if len(secret) <= _VISIBLE_PREFIX:
        return MASK
    return secret[:_VISIBLE_PREFIX] + MASK


def redact_text(text: str, secrets: Iterable[str]) -> str:
    """Mask private-key bodies and every occurrence of the given secrets."""
    text = _PRIVATE_KEY_RE.sub(lambda m: m.group(1) + MASK + m.group(3), text)
    # Longest first, so a secret that contains a shorter one is masked whole.
    for secret in sorted(set(secrets), key=len, reverse=True):
        masked = mask_secret(secret)
        # Only whole occurrences: "abc" is not masked inside "abcdef".
        pattern = re.compile(r"(?<![A-Za-z0-9])" + re.escape(secret) + r"(?![A-Za-z0-9])")
        text = pattern.sub(lambda _match: masked, text)
    return text


def _text_fields(finding: Finding) -> list[str]:
    return [finding.title, finding.evidence, finding.recommendation]


def _redact_finding(finding: Finding, secrets: set[str]) -> Finding:
    return replace(
        finding,
        title=redact_text(finding.title, secrets),
        evidence=redact_text(finding.evidence, secrets),
        recommendation=redact_text(finding.recommendation, secrets),
    )


def redact_report(report: AuditReport) -> AuditReport:
    """Return a copy of `report` that is safe to display or write to a file."""
    all_findings = report.findings + report.ignored_findings
    texts = [text for finding in all_findings for text in _text_fields(finding)]
    if report.task:
        texts.append(report.task)

    secrets: set[str] = set()
    for text in texts:
        secrets.update(secret_values(text))

    return replace(
        report,
        task=redact_text(report.task, secrets) if report.task else report.task,
        findings=[_redact_finding(f, secrets) for f in report.findings],
        ignored_findings=[_redact_finding(f, secrets) for f in report.ignored_findings],
    )
