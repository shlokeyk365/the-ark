"""Server-only, non-executable local settings. Never return credentials to clients."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_SETTING_NAMES = {
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_MODEL",
    "ANTHROPIC_WORKSPACE_ID",
    "OPENROUTER_API_KEY",
}
_OPENROUTER_MODELS = {
    "claude-sonnet-4-6": "anthropic/claude-sonnet-4.6",
    "claude-sonnet-4.6": "anthropic/claude-sonnet-4.6",
}


def _local_settings() -> dict[str, str]:
    values = {}
    local = ROOT / ".env.local"
    if local.is_file():
        for line in local.read_text(encoding="utf-8-sig").splitlines():
            name, separator, value = line.partition("=")
            if separator and name.strip() in _SETTING_NAMES:
                values[name.strip()] = value.strip().strip("\"'")
    return values


def claude_workspace() -> str:
    return os.getenv("ANTHROPIC_WORKSPACE_ID", _local_settings().get("ANTHROPIC_WORKSPACE_ID", "")).strip()


def claude_settings() -> tuple[str, str]:
    values = _local_settings()
    key = os.getenv(
        "ANTHROPIC_API_KEY",
        os.getenv("OPENROUTER_API_KEY", values.get("ANTHROPIC_API_KEY", values.get("OPENROUTER_API_KEY", ""))),
    )
    model = os.getenv("ANTHROPIC_MODEL", values.get("ANTHROPIC_MODEL", "claude-sonnet-4-6"))
    if key.startswith("PASTE_"):
        key = ""
    return key.strip(), model.strip()


def claude_provider(key: str, model: str) -> tuple[str, dict[str, str], str, str]:
    """Return URL, headers, model id, and provider name for the Messages call."""
    if key.startswith(("AIza", "AQ.")):
        mapped = model if model.startswith("gemini") else "gemini-3.6-flash"
        return (
            f"https://generativelanguage.googleapis.com/v1beta/models/{mapped}:generateContent",
            {"x-goog-api-key": key, "Content-Type": "application/json"},
            mapped,
            "gemini",
        )
    if key.startswith("sk-or-"):
        mapped = model if model.startswith("anthropic/") else _OPENROUTER_MODELS.get(model, f"anthropic/{model}")
        return (
            "https://openrouter.ai/api/v1/messages",
            {
                "Authorization": f"Bearer {key}",
                "anthropic-version": "2023-06-01",
                "HTTP-Referer": "http://127.0.0.1:5173",
                "X-Title": "the ark",
            },
            mapped,
            "anthropic",
        )
    headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
    workspace = claude_workspace()
    if workspace:
        headers["anthropic-workspace-id"] = workspace
    return "https://api.anthropic.com/v1/messages", headers, model, "anthropic"
