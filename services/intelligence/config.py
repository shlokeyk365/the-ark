"""Server-only, non-executable local settings. Never return credentials to clients."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _local_settings() -> dict[str, str]:
    values = {}
    local = ROOT / ".env.local"
    if local.is_file():
        for line in local.read_text(encoding="utf-8-sig").splitlines():
            name, separator, value = line.partition("=")
            if separator and name.strip() in {"ANTHROPIC_API_KEY", "ANTHROPIC_MODEL", "ANTHROPIC_WORKSPACE_ID"}:
                values[name.strip()] = value.strip().strip("\"'")
    return values


def claude_workspace() -> str:
    return os.getenv("ANTHROPIC_WORKSPACE_ID", _local_settings().get("ANTHROPIC_WORKSPACE_ID", "")).strip()


def claude_settings() -> tuple[str, str]:
    values = _local_settings()
    key = os.getenv("ANTHROPIC_API_KEY", values.get("ANTHROPIC_API_KEY", ""))
    model = os.getenv("ANTHROPIC_MODEL", values.get("ANTHROPIC_MODEL", "claude-sonnet-4-6"))
    if key.startswith("PASTE_"):
        key = ""
    return key.strip(), model.strip()
