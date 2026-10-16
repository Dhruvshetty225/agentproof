"""Optional per-repository configuration from ``.agentproof.toml``.

Example file:

    [rules]
    disable = ["SCOPE001"]        # rules that do not run at all

    [severity]
    TESTCOV001 = "low"            # low | medium | high | critical

    [thresholds]
    review = 40                   # score >= review  -> REVIEW
    reject = 70                   # score >= reject  -> REJECT

Every section and key is optional. Anything left out keeps its default.

Discovery and precedence (the first that applies wins; files are never merged):

1. ``--config PATH`` on the command line: that file is read from disk.
2. ``.agentproof.toml`` at the root of the *base* revision (for example
   ``main``), read through git. It is read from the base, not from the branch
   being audited, so a change cannot loosen its own audit by editing the file.
3. Built-in defaults: all rules enabled, built-in severities, review at 30,
   reject at 60.

Validation errors (unknown sections/keys, unknown rule IDs, invalid
severities, thresholds that are not whole numbers in 1-100 or where review is
not below reject) raise ConfigError instead of being silently ignored.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

from git import Repo

from agentproof.rules import ALL_RULES
from agentproof.schema import MAX_RISK_SCORE, Severity

if sys.version_info >= (3, 11):
    import tomllib
else:  # Python 3.9 and 3.10 need the tomli backport
    import tomli as tomllib

CONFIG_FILE_NAME = ".agentproof.toml"
DEFAULT_REVIEW_THRESHOLD = 30
DEFAULT_REJECT_THRESHOLD = 60
KNOWN_RULE_IDS = tuple(rule.RULE_ID for rule in ALL_RULES)

_SECTIONS = {"rules", "severity", "thresholds"}
_SEVERITIES = {severity.value: severity for severity in Severity}


class ConfigError(ValueError):
    """The configuration file is missing, unreadable or invalid."""


@dataclass(frozen=True)
class Config:
    disabled_rules: frozenset[str] = frozenset()
    severity_overrides: dict[str, Severity] = field(default_factory=dict)
    review_threshold: int = DEFAULT_REVIEW_THRESHOLD
    reject_threshold: int = DEFAULT_REJECT_THRESHOLD
    source: str = "built-in defaults"


# --- discovery ----------------------------------------------------------------


def load_config(repo_path: str, base: str, config_path: str | None = None) -> Config:
    """Find and parse the configuration that applies to this audit."""
    if config_path is not None:
        try:
            text = Path(config_path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise ConfigError(f"cannot read config file {config_path}: {exc}") from exc
        return parse_config(text, source=config_path)

    text = _read_from_base(repo_path, base)
    if text is None:
        return Config()
    return parse_config(text, source=f"{CONFIG_FILE_NAME} on {base}")


def _read_from_base(repo_path: str, base: str) -> str | None:
    tree = Repo(repo_path).commit(base).tree
    try:
        blob = tree / CONFIG_FILE_NAME
    except KeyError:
        return None
    try:
        return blob.data_stream.read().decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ConfigError(f"{CONFIG_FILE_NAME} on {base} is not valid UTF-8") from exc


# --- parsing and validation ---------------------------------------------------


def parse_config(text: str, source: str) -> Config:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{source}: not valid TOML ({exc})") from exc

    _check_keys(data, _SECTIONS, source)
    rules = _table(data, "rules", source)
    _check_keys(rules, {"disable"}, f"{source} [rules]")
    severity = _table(data, "severity", source)
    thresholds = _table(data, "thresholds", source)
    _check_keys(thresholds, {"review", "reject"}, f"{source} [thresholds]")

    review = _threshold(thresholds.get("review", DEFAULT_REVIEW_THRESHOLD), "review", source)
    reject = _threshold(thresholds.get("reject", DEFAULT_REJECT_THRESHOLD), "reject", source)
    if review >= reject:
        raise ConfigError(
            f"{source} [thresholds]: review ({review}) must be lower than reject ({reject})"
        )

    return Config(
        disabled_rules=frozenset(_disabled_rules(rules.get("disable", []), source)),
        severity_overrides={
            _rule_id(rule_id, f"{source} [severity]"): _severity(value, rule_id, source)
            for rule_id, value in severity.items()
        },
        review_threshold=review,
        reject_threshold=reject,
        source=source,
    )


def _check_keys(table: dict, allowed: set[str], where: str) -> None:
    unknown = sorted(set(table) - allowed)
    if unknown:
        raise ConfigError(
            f"{where}: unknown key(s) {', '.join(unknown)}; "
            f"allowed: {', '.join(sorted(allowed))}"
        )


def _table(data: dict, name: str, source: str) -> dict:
    value = data.get(name, {})
    if not isinstance(value, dict):
        raise ConfigError(f"{source}: [{name}] must be a table")
    return value


def _rule_id(value: object, where: str) -> str:
    if value not in KNOWN_RULE_IDS:
        raise ConfigError(
            f"{where}: unknown rule ID {value!r}; known rules: {', '.join(KNOWN_RULE_IDS)}"
        )
    return value


def _disabled_rules(value: object, source: str) -> list[str]:
    where = f"{source} [rules] disable"
    if not isinstance(value, list):
        raise ConfigError(f"{where}: must be a list of rule IDs")
    return [_rule_id(rule_id, where) for rule_id in value]


def _severity(value: object, rule_id: str, source: str) -> Severity:
    if not isinstance(value, str) or value not in _SEVERITIES:
        raise ConfigError(
            f"{source} [severity] {rule_id}: invalid severity {value!r}; "
            f"use one of {', '.join(_SEVERITIES)}"
        )
    return _SEVERITIES[value]


def _threshold(value: object, name: str, source: str) -> int:
    # bool is a subclass of int in Python, so reject it explicitly.
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_RISK_SCORE:
        raise ConfigError(
            f"{source} [thresholds] {name}: must be a whole number from 1 to {MAX_RISK_SCORE}, "
            f"got {value!r}"
        )
    return value
