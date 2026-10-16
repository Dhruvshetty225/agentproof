"""SARIF 2.1.0 output (sarif.py).

Schema validation uses the official OASIS schema, which is not committed
(see scripts/fetch_sarif_schema.sh). If it has not been downloaded, the
validation tests are reported as SKIPPED, not as passed. If the cached copy
does not match the pinned checksum, they ERROR instead of validating against
an unknown schema.
"""

import hashlib
import json
from pathlib import Path

import pytest

from agentproof.rules import ALL_RULES
from agentproof.sarif import render_sarif
from agentproof.schema import AuditReport, DiffSide, Finding, MergeRecommendation, Severity

ROOT_DIR = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT_DIR / "tests" / "schemas" / "sarif-schema-2.1.0.json"
FETCH_SCRIPT = ROOT_DIR / "scripts" / "fetch_sarif_schema.sh"
# Must equal EXPECTED_SHA256 in scripts/fetch_sarif_schema.sh (checked below).
SCHEMA_SHA256 = "c3b4bb2d6093897483348925aaa73af03b3e3f4bd4ca38cef26dcb4212a2682e"
FAKE_KEY = "sk-" + "abcd1234efgh"


def _report(findings=(), ignored=()) -> AuditReport:
    return AuditReport(
        repo_path=".",
        base="main",
        branch="feature",
        task=None,
        findings=list(findings),
        ignored_findings=list(ignored),
        risk_score=60,
        recommendation=MergeRecommendation.REJECT,
    )


DELETED = Finding(
    "AUTH001", Severity.HIGH, "Security-relevant code was deleted", "app/auth.py", 57,
    "if is_expired(token):\nraise ValueError('expired')", "Confirm.",
    side=DiffSide.OLD, end_line_number=58,
)
ADDED = Finding(
    "SECRET001", Severity.CRITICAL, "Hardcoded credential added to source code",
    "app/config.py", 7, f'api_key = "{FAKE_KEY}"', "Remove it.", side=DiffSide.NEW,
)
MULTI_FILE = Finding(
    "TESTCOV001", Severity.MEDIUM, "No test update", "app/a.py, app/b.py", None, "e", "r",
    paths=("app/a.py", "app/b.py"),
)
WHOLE_FILE = Finding("UNREVIEWABLE001", Severity.LOW, "Renamed", "app/new.py", None, "e", "r")
IGNORED = Finding("LOG001", Severity.HIGH, "Logged", "app/log.py", 4, "print(token)", "r",
                  side=DiffSide.NEW)


def _sarif(report: AuditReport) -> dict:
    return json.loads(render_sarif(report))


def _results(*findings) -> list:
    return _sarif(_report(findings))["runs"][0]["results"]


# --- schema validation -------------------------------------------------------------------


def _load_verified_schema(path: Path) -> dict:
    """Load the cached schema, failing loudly unless it is the pinned version.

    The fetch script checks the checksum when it downloads the file; this
    checks it again every time the tests use the cached copy, so an edited or
    corrupted cache can never be used for validation.
    """
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != SCHEMA_SHA256:
        pytest.fail(
            f"Cached SARIF schema {path} does not match the pinned checksum "
            f"(expected {SCHEMA_SHA256}, got {actual}). Re-run "
            "scripts/fetch_sarif_schema.sh. SARIF schema validation was NOT performed."
        )
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def sarif_validator():
    jsonschema = pytest.importorskip("jsonschema")
    if not SCHEMA_PATH.exists():
        pytest.skip(
            "SARIF schema not downloaded; run scripts/fetch_sarif_schema.sh. "
            "SARIF schema validation was NOT performed."
        )
    return jsonschema.Draft4Validator(_load_verified_schema(SCHEMA_PATH))


def test_pinned_checksum_matches_the_fetch_script():
    script = FETCH_SCRIPT.read_text(encoding="utf-8")
    assert f'EXPECTED_SHA256="{SCHEMA_SHA256}"' in script


def test_tampered_schema_cache_fails_instead_of_validating(tmp_path):
    # A permissive schema that would accept any document: the dangerous case.
    tampered = tmp_path / "sarif-schema-2.1.0.json"
    tampered.write_text('{"type": "object"}', encoding="utf-8")
    with pytest.raises(pytest.fail.Exception, match="validation was NOT performed"):
        _load_verified_schema(tampered)


@pytest.mark.parametrize(
    "report",
    [
        _report([DELETED, ADDED, MULTI_FILE, WHOLE_FILE], ignored=[IGNORED]),
        _report(),
    ],
    ids=["all-finding-kinds", "empty"],
)
def test_output_is_valid_against_the_official_sarif_schema(sarif_validator, report):
    errors = sorted(sarif_validator.iter_errors(_sarif(report)), key=str)
    assert errors == [], [error.message for error in errors]


def test_schema_validation_catches_an_invalid_document(sarif_validator):
    # Guards against a validator that accepts everything.
    broken = _sarif(_report([ADDED]))
    broken["runs"][0]["results"][0]["level"] = "fatal"
    assert list(sarif_validator.iter_errors(broken))


# --- structure ---------------------------------------------------------------------------


def test_header_and_tool_metadata():
    sarif = _sarif(_report())
    assert sarif["version"] == "2.1.0"
    driver = sarif["runs"][0]["tool"]["driver"]
    assert driver["name"] == "AgentProof"
    assert [rule["id"] for rule in driver["rules"]] == [rule.RULE_ID for rule in ALL_RULES]
    for rule in driver["rules"]:
        assert rule["shortDescription"]["text"]
        assert rule["fullDescription"]["text"]


def test_run_properties_carry_score_and_recommendation():
    properties = _sarif(_report())["runs"][0]["properties"]
    assert properties["riskScore"] == 60
    assert properties["recommendation"] == "reject"
    assert (properties["base"], properties["branch"]) == ("main", "feature")


@pytest.mark.parametrize(
    "severity, level",
    [
        (Severity.CRITICAL, "error"),
        (Severity.HIGH, "error"),
        (Severity.MEDIUM, "warning"),
        (Severity.LOW, "note"),
    ],
)
def test_severity_maps_to_sarif_level(severity, level):
    finding = Finding("SECRET001", severity, "t", "a.py", 1, "e", "r", side=DiffSide.NEW)
    result = _results(finding)[0]
    assert result["level"] == level
    assert result["properties"]["severity"] == severity.value


def test_rule_index_points_at_the_matching_rule():
    sarif = _sarif(_report([ADDED]))
    rules = sarif["runs"][0]["tool"]["driver"]["rules"]
    result = sarif["runs"][0]["results"][0]
    assert rules[result["ruleIndex"]]["id"] == "SECRET001"


# --- locations ------------------------------------------------------------------------------


def test_added_line_has_a_region_in_the_current_file():
    location = _results(ADDED)[0]["locations"][0]["physicalLocation"]
    assert location["artifactLocation"] == {"uri": "app/config.py", "uriBaseId": "%SRCROOT%"}
    assert location["region"] == {"startLine": 7}


def test_deleted_lines_are_not_presented_as_current_file_lines():
    result = _results(DELETED)[0]
    location = result["locations"][0]["physicalLocation"]
    assert location["artifactLocation"]["uri"] == "app/auth.py"
    assert "region" not in location
    assert result["properties"]["diffSide"] == "old"
    assert result["properties"]["baseStartLine"] == 57
    assert result["properties"]["baseEndLine"] == 58
    assert "base version (main)" in result["message"]["text"]


def test_multi_file_finding_points_at_each_file():
    locations = _results(MULTI_FILE)[0]["locations"]
    uris = [loc["physicalLocation"]["artifactLocation"]["uri"] for loc in locations]
    assert uris == ["app/a.py", "app/b.py"]


def test_uris_are_relative_and_percent_encoded():
    finding = Finding("UNREVIEWABLE001", Severity.LOW, "t", "my dir/a b#1.py", None, "e", "r")
    uri = _results(finding)[0]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
    assert uri == "my%20dir/a%20b%231.py"
    assert not uri.startswith("/")


# --- suppressions and redaction -----------------------------------------------------------


def test_ignored_findings_are_included_as_suppressed():
    results = _sarif(_report([ADDED], ignored=[IGNORED]))["runs"][0]["results"]
    assert "suppressions" not in results[0]
    assert results[1]["ruleId"] == "LOG001"
    assert results[1]["suppressions"][0]["kind"] == "inSource"


def test_sarif_is_redacted():
    text = render_sarif(_report([ADDED]))
    assert FAKE_KEY not in text
    assert "sk-a****" in text
