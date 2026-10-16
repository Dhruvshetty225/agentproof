"""AI coding-agent GitHub Apps whose pull requests count as AI-authored.

Evidence standard: a pull request is included only if its author is one of
these bot accounts and the GitHub API reports the author's type as "Bot"
with the bot ID listed here. A GitHub App bot account can only be operated
by its app, so this is verifiable provenance, unlike a human-applied label.

Every entry was checked on 2026-10-16 with the public GitHub API:
``GET /users/<slug>[bot]`` (login, id, type == "Bot") and ``GET /apps/<slug>``
(app name, owning organization, external URL). Apps that rarely author pull
requests themselves were left out (chatgpt-codex-connector authored 4 public
PRs; Codex PRs are normally opened under the user's own account).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentApp:
    slug: str  # GitHub App slug, used in search as author:app/<slug>
    bot_login: str  # pull request author login reported by the API
    bot_id: int
    owner: str  # organization that owns the GitHub App
    agent: str  # human-readable product name

    @property
    def app_url(self) -> str:
        return f"https://github.com/apps/{self.slug}"


AGENT_APPS = [
    AgentApp("copilot-swe-agent", "Copilot", 198982749, "github", "GitHub Copilot coding agent"),
    AgentApp("devin-ai-integration", "devin-ai-integration[bot]", 158243242, "usacognition", "Devin"),
    AgentApp("google-labs-jules", "google-labs-jules[bot]", 161369871, "google-labs-code", "Jules"),
    AgentApp("cursor", "cursor[bot]", 206951365, "cursor", "Cursor background agent"),
    AgentApp("claude", "claude[bot]", 209825114, "anthropics", "Claude Code"),
    AgentApp("amazon-q-developer", "amazon-q-developer[bot]", 208079219, "Amazon-Q-Developer", "Amazon Q Developer"),
    AgentApp("codegen-sh", "codegen-sh[bot]", 131295404, "codegen-sh", "Codegen"),
]
