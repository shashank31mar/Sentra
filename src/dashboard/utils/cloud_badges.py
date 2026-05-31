"""Shared cloud-platform badge map.

Single source of truth for the emoji + label used in the cross-cloud inventory
table and timeline. Issue #11 from Kiro's M4 review — the map used to be
duplicated in agents_tab.py and overview_tab.py and would drift the moment one
needed a new platform.

Keys match `Platform` enum values from `src/connectors/base/models.py`.
"""

from __future__ import annotations


PLATFORM_BADGES: dict[str, str] = {
    "bedrock": "🟧 AWS Bedrock",
    "azure_foundry": "🟦 Azure Foundry",
    "vertex_ai": "🟩 GCP Vertex",
    "unknown": "⬜ Unknown",
}


def badge_for(platform: str | None) -> str:
    """Return the human-facing badge for a platform key, falling back to the raw value."""
    if not platform:
        return PLATFORM_BADGES["unknown"]
    return PLATFORM_BADGES.get(platform, platform)
