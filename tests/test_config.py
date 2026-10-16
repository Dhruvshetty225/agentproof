"""Optional .agentproof.toml configuration."""

import io

import pytest
from rich.console import Console
from typer.testing import CliRunner

from agentproof import cli
from agentproof.config import Config, ConfigError, load_config, parse_config
from agentproof.diff_parser import ChangedLine, FileDiff
from agentproof.engine import collect_findings, run_audit
from agentproof.schema import MergeRecommendation, Severity
from tests.git_helpers import make_repo

FULL_CONFIG = """
[rules]
disable = ["SCOPE001", "TESTCOV001"]

[severity]
LOG001 = "low"
AUTH001 = "critical"

[thresholds]
review = 40
reject = 70
"""


# --- parsing ---------------------------------------------------------------------


def test_empty_file_gives_the_defaults():
    config = parse_config("", source="test")
    assert config.disabled_rules == frozenset()
    assert config.severity_overrides == {}
    assert (config.review_threshold, config.reject_threshold) == (30, 60)


def test_full_config_is_parsed():
    config = parse_config(FULL_CONFIG, source="test")
    assert config.disabled_rules == {"SCOPE001", "TESTCOV001"}
    assert config.severity_overrides == {"LOG001": Severity.LOW, "AUTH001": Severity.CRITICAL}
    assert (config.review_threshold, config.reject_threshold) == (40, 70)
    assert config.source == "test"


def test_one_threshold_can_be_set_alone():
    config = parse_config("[thresholds]\nreject = 90\n", source="test")
    assert (config.review_threshold, config.reject_threshold) == (30, 90)


# --- validation ------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, message",
    [
        ("[rules\n", "not valid TOML"),
        ("[threshold]\nreview = 10\n", "unknown key(s) threshold"),
        ("[rules]\nenable = []\n", "unknown key(s) enable"),
        ("[thresholds]\nwarn = 10\n", "unknown key(s) warn"),
        ('[rules]\ndisable = ["AUTH999"]\n', "unknown rule ID 'AUTH999'"),
        ('[rules]\ndisable = ["auth001"]\n', "unknown rule ID 'auth001'"),
        ('[rules]\ndisable = "SCOPE001"\n', "must be a list"),
        ('[severity]\nNOPE001 = "low"\n', "unknown rule ID 'NOPE001'"),
        ('[severity]\nLOG001 = "severe"\n', "invalid severity 'severe'"),
        ('[severity]\nLOG001 = "LOW"\n', "invalid severity 'LOW'"),
        ("[severity]\nLOG001 = 3\n", "invalid severity 3"),
        ('[severity]\nLOG001 = ["low"]\n', "invalid severity"),
        ("rules = 5\n", "[rules] must be a table"),
        ("[thresholds]\nreview = 60\nreject = 60\n", "review (60) must be lower than reject (60)"),
        ("[thresholds]\nreview = 80\nreject = 50\n", "must be lower than reject"),
        ("[thresholds]\nreview = 70\n", "review (70) must be lower than reject (60)"),
        ("[thresholds]\nreview = 0\n", "whole number from 1 to 100"),
        ("[thresholds]\nreject = 101\n", "whole number from 1 to 100"),
        ("[thresholds]\nreview = 12.5\n", "whole number from 1 to 100"),
        ('[thresholds]\nreview = "30"\n', "whole number from 1 to 100"),
        ("[thresholds]\nreview = true\n", "whole number from 1 to 100"),
    ],
)
def test_invalid_config_is_rejected_with_a_clear_message(text, message):
    with pytest.raises(ConfigError) as error:
        parse_config(text, source="cfg.toml")
    assert message in str(error.value)
    assert "cfg.toml" in str(error.value)


# --- discovery and precedence ----------------------------------------------------


def test_no_config_file_means_defaults(tmp_path):
    repo = make_repo(tmp_path / "repo", {"app.py": "x = 1\n"}, {"app.py": "x = 2\n"})
    assert load_config(repo, "main") == Config()


def test_config_is_read_from_the_base_branch(tmp_path):
    repo = make_repo(
        tmp_path / "repo",
        {".agentproof.toml": '[rules]\ndisable = ["SCOPE001"]\n'},
        {"app.py": "x = 1\n"},
    )
    config = load_config(repo, "main")
    assert config.disabled_rules == {"SCOPE001"}
    assert config.source == ".agentproof.toml on main"


def test_config_added_by_the_audited_branch_is_not_used(tmp_path):
    repo = make_repo(
        tmp_path / "repo",
        {"app.py": "x = 1\n"},
        {".agentproof.toml": '[rules]\ndisable = ["AUTH001", "SECRET001"]\n'},
    )
    assert load_config(repo, "main") == Config()


def test_branch_cannot_loosen_the_base_config(tmp_path):
    repo = make_repo(
        tmp_path / "repo",
        {".agentproof.toml": '[rules]\ndisable = ["SCOPE001"]\n'},
        {".agentproof.toml": '[rules]\ndisable = ["SCOPE001", "AUTH001"]\n'},
    )
    assert load_config(repo, "main").disabled_rules == {"SCOPE001"}


def test_explicit_config_path_takes_precedence_over_the_base_file(tmp_path):
    repo = make_repo(
        tmp_path / "repo",
        {".agentproof.toml": '[rules]\ndisable = ["SCOPE001"]\n'},
        {"app.py": "x = 1\n"},
    )
    explicit = tmp_path / "custom.toml"
    explicit.write_text('[rules]\ndisable = ["LOG001"]\n', encoding="utf-8")
    config = load_config(repo, "main", str(explicit))
    assert config.disabled_rules == {"LOG001"}
    assert config.source == str(explicit)


def test_missing_explicit_config_path_is_an_error(tmp_path):
    repo = make_repo(tmp_path / "repo", {"app.py": "x = 1\n"}, {"app.py": "x = 2\n"})
    with pytest.raises(ConfigError, match="cannot read config file"):
        load_config(repo, "main", str(tmp_path / "missing.toml"))


def test_invalid_base_config_is_an_error_not_silently_ignored(tmp_path):
    repo = make_repo(
        tmp_path / "repo",
        {".agentproof.toml": '[severity]\nLOG001 = "severe"\n'},
        {"app.py": "x = 1\n"},
    )
    with pytest.raises(ConfigError, match=".agentproof.toml on main"):
        load_config(repo, "main")


# --- effect on the audit -----------------------------------------------------------


def _secret_and_log_diff() -> list:
    return [
        FileDiff(
            file_path="app/config.py",
            added_lines=[
                ChangedLine(1, 'db_password = "hunter2"'),
                ChangedLine(2, "logger.info(token)"),
            ],
        )
    ]


def test_disabled_rule_does_not_run():
    config = parse_config('[rules]\ndisable = ["SECRET001"]\n', source="test")
    findings, _ = collect_findings(_secret_and_log_diff(), config=config)
    assert {f.rule_id for f in findings} == {"LOG001", "TESTCOV001"}


def test_severity_override_changes_only_that_rule():
    config = parse_config('[severity]\nLOG001 = "low"\n', source="test")
    findings, _ = collect_findings(_secret_and_log_diff(), config=config)
    severities = {f.rule_id: f.severity for f in findings}
    assert severities["LOG001"] == Severity.LOW
    assert severities["SECRET001"] == Severity.HIGH


def test_default_config_matches_running_without_config():
    with_default, _ = collect_findings(_secret_and_log_diff(), config=Config())
    without, _ = collect_findings(_secret_and_log_diff())
    assert with_default == without


def test_thresholds_change_the_recommendation(tmp_path):
    repo = make_repo(
        tmp_path / "repo",
        {"app/config.py": "x = 1\n"},
        {"app/config.py": 'x = 1\ndb_password = "hunter2"\n'},
    )
    # SECRET001 (high, 20) + TESTCOV001 (medium, 10) = 30 points.
    default = run_audit(repo, "main", "feature")
    assert default.risk_score == 30
    assert default.recommendation == MergeRecommendation.REVIEW

    lenient = parse_config("[thresholds]\nreview = 40\nreject = 70\n", source="test")
    assert run_audit(repo, "main", "feature", config=lenient).recommendation == (
        MergeRecommendation.APPROVE
    )

    strict = parse_config("[thresholds]\nreview = 10\nreject = 25\n", source="test")
    assert run_audit(repo, "main", "feature", config=strict).recommendation == (
        MergeRecommendation.REJECT
    )


# --- command line ------------------------------------------------------------------


def test_cli_reports_config_errors_with_exit_code_2(tmp_path):
    repo = make_repo(
        tmp_path / "repo",
        {".agentproof.toml": '[rules]\ndisable = ["AUTH999"]\n'},
        {"app.py": "x = 1\n"},
    )
    result = CliRunner().invoke(
        cli.app,
        ["audit", "--repo", repo, "--branch", "feature", "--output", str(tmp_path / "r.html")],
    )
    assert result.exit_code == 2
    # Errors go to standard error, and "[rules]" is printed literally rather
    # than being swallowed as Rich markup.
    assert "Configuration error: .agentproof.toml on main [rules] disable" in result.stderr
    assert result.stdout == ""
    assert not (tmp_path / "r.html").exists()


def test_cli_uses_the_explicit_config_and_shows_its_source(tmp_path, monkeypatch):
    output = io.StringIO()
    monkeypatch.setattr(cli, "console", Console(file=output, width=400, no_color=True))
    repo = make_repo(tmp_path / "repo", {"app.py": "x = 1\n"}, {"app.py": "x = 2\n"})
    explicit = tmp_path / "custom.toml"
    explicit.write_text('[rules]\ndisable = ["TESTCOV001"]\n', encoding="utf-8")
    result = CliRunner().invoke(
        cli.app, ["audit", "--repo", repo, "--branch", "feature", "--config", str(explicit)]
    )
    assert result.exit_code == 0
    assert f"Config: {explicit}" in output.getvalue()
    assert "TESTCOV001" not in output.getvalue()
