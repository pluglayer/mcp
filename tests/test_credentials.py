from pathlib import Path

import pytest

from pluglayer_mcp.client import PlugLayerClient
from pluglayer_mcp.credentials import resolve_api_base_url, resolve_api_key
from pluglayer_mcp.settings import settings


def _write_credentials(path: Path, token: str, api_url: str = "") -> None:
    path.write_text(
        "\n".join(
            [
                f"export PLUGLAYER_API_KEY={token}",
                f"export PLUGLAYER_API_URL={api_url}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_client_rereads_configured_credential_file(monkeypatch, tmp_path):
    credentials = tmp_path / "credentials.env"
    monkeypatch.setenv("PLUGLAYER_CREDENTIALS_FILE", str(credentials))
    monkeypatch.setenv("PLUGLAYER_API_KEY", "stale-parent-token")
    _write_credentials(credentials, "first-saved-token")

    client = PlugLayerClient()
    assert client.headers["Authorization"] == "Bearer first-saved-token"

    _write_credentials(credentials, "refreshed-saved-token")
    assert client.headers["Authorization"] == "Bearer refreshed-saved-token"


def test_client_rereads_default_credential_file_without_reload(monkeypatch, tmp_path):
    credentials = tmp_path / ".pluglayer" / "credentials.env"
    credentials.parent.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("PLUGLAYER_CREDENTIALS_FILE", raising=False)
    monkeypatch.setattr(settings, "PLUGLAYER_CREDENTIALS_FILE", "")
    monkeypatch.setenv("PLUGLAYER_API_KEY", "stale-parent-token")
    _write_credentials(
        credentials,
        "first-saved-token",
        "https://api.first.example.test",
    )

    client = PlugLayerClient()
    assert client.headers["Authorization"] == "Bearer first-saved-token"
    assert client.base_url == "https://api.first.example.test"

    _write_credentials(
        credentials,
        "refreshed-saved-token",
        "https://api.refreshed.example.test/",
    )
    assert client.headers["Authorization"] == "Bearer refreshed-saved-token"
    assert client.base_url == "https://api.refreshed.example.test"


def test_saved_api_url_uses_same_dynamic_credential_file(monkeypatch, tmp_path):
    credentials = tmp_path / "credentials.env"
    monkeypatch.setenv("PLUGLAYER_CREDENTIALS_FILE", str(credentials))
    _write_credentials(
        credentials,
        "saved-token",
        "https://api.staging.example.test/ ",
    )

    assert resolve_api_base_url() == "https://api.staging.example.test/"


def test_missing_token_fails_before_empty_bearer_is_constructed():
    client = PlugLayerClient(api_key="")

    with pytest.raises(RuntimeError, match="authentication is not configured"):
        _ = client.headers


def test_whitespace_token_fails_before_empty_bearer_is_constructed():
    with pytest.raises(RuntimeError, match="authentication is not configured"):
        resolve_api_key(" \t ")


def test_empty_saved_token_does_not_fall_back_to_stale_environment(monkeypatch, tmp_path):
    credentials = tmp_path / "credentials.env"
    _write_credentials(credentials, "")
    monkeypatch.setenv("PLUGLAYER_CREDENTIALS_FILE", str(credentials))
    monkeypatch.setenv("PLUGLAYER_API_KEY", "stale-parent-token")

    with pytest.raises(RuntimeError, match="authentication is not configured"):
        resolve_api_key()


def test_missing_auth_explains_local_mcp_auth_and_retry(monkeypatch, tmp_path):
    monkeypatch.setenv("PLUGLAYER_CREDENTIALS_FILE", str(tmp_path / "missing.env"))
    monkeypatch.delenv("PLUGLAYER_API_KEY", raising=False)
    monkeypatch.setattr(settings, "PLUGLAYER_API_KEY", "")

    with pytest.raises(RuntimeError) as exc_info:
        resolve_api_key()

    message = str(exc_info.value)
    assert "mcp_auth" in message
    assert "reload is not required" in message


def test_control_characters_are_rejected_without_echoing_the_token():
    unsafe = "secret-token\r\ninjected"

    with pytest.raises(RuntimeError, match="control character") as exc_info:
        resolve_api_key(unsafe)

    assert unsafe not in str(exc_info.value)


def test_shell_quoted_saved_token_is_supported(monkeypatch, tmp_path):
    credentials = tmp_path / "credentials.env"
    credentials.write_text(
        "export PLUGLAYER_API_KEY='quoted-token'\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PLUGLAYER_CREDENTIALS_FILE", str(credentials))

    assert resolve_api_key() == "quoted-token"
