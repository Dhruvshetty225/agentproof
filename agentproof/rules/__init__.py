"""Rule-based checks that AgentProof runs against a diff."""

from agentproof.rules import (
    auth,
    logging_safety,
    secrets,
    test_coverage,
    unrelated_changes,
    unreviewable_changes,
)

ALL_RULES = [
    auth,
    secrets,
    logging_safety,
    test_coverage,
    unrelated_changes,
    unreviewable_changes,
]

__all__ = ["ALL_RULES"]
