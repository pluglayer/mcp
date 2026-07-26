"""Runtime credential resolution for local MCP/editor integrations."""

from __future__ import annotations

import os
import shlex
from pathlib import Path

from pluglayer_mcp.settings import settings

_AUTH_CONFIGURATION_ERROR = (
    "PlugLayer authentication is not configured. Add a PlugLayer API token, "
    "then restart or reload the MCP server."
)
_UNSAFE_TOKEN_ERROR = (
    "PlugLayer authentication is invalid because the configured API token "
    "contains a control character. Save the token again, then restart or "
    "reload the MCP server."
)


def _credential_file_path() -> Path | None:
    configured = (
        os.environ.get("PLUGLAYER_CREDENTIALS_FILE")
        or settings.PLUGLAYER_CREDENTIALS_FILE
    ).strip()
    if not configured:
        return None
    expanded = os.path.expandvars(os.path.expanduser(configured))
    return Path(expanded)


def _parse_assignment(line: str, key: str) -> str | None:
    candidate = line.strip()
    if not candidate or candidate.startswith("#"):
        return None
    if candidate.startswith("export "):
        candidate = candidate[7:].lstrip()
    name, separator, raw_value = candidate.partition("=")
    if not separator or name.strip() != key:
        return None
    try:
        parsed = shlex.split(raw_value.strip(), posix=True)
    except ValueError:
        return None
    if len(parsed) != 1:
        return None
    return parsed[0]


def _read_saved_value(key: str) -> str | None:
    path = _credential_file_path()
    if path is None:
        return None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    resolved = None
    for line in lines:
        value = _parse_assignment(line, key)
        if value is not None:
            resolved = value
    return resolved


def _runtime_value(key: str, settings_value: str) -> str:
    saved = _read_saved_value(key)
    if saved is not None:
        return saved
    return os.environ.get(key, settings_value)


def resolve_api_key(explicit: str | None = None) -> str:
    """Return a safe current token, preferring a configured live credential file."""
    raw_value = (
        explicit
        if explicit is not None
        else _runtime_value("PLUGLAYER_API_KEY", settings.PLUGLAYER_API_KEY)
    )
    token = (raw_value or "").strip()
    if not token:
        raise RuntimeError(_AUTH_CONFIGURATION_ERROR)
    if any(ord(character) < 32 or ord(character) == 127 for character in token):
        raise RuntimeError(_UNSAFE_TOKEN_ERROR)
    return token


def resolve_api_base_url(explicit: str | None = None) -> str:
    """Resolve the API base URL from the same live source as the token."""
    raw_value = (
        explicit
        if explicit is not None
        else _runtime_value("PLUGLAYER_API_URL", settings.PLUGLAYER_API_URL)
    )
    candidate = (raw_value or "").strip()
    return candidate or "https://api.pluglayer.com"


def is_api_key_configured() -> bool:
    try:
        resolve_api_key()
    except RuntimeError:
        return False
    return True
