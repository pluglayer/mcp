from pluglayer_mcp.tools.deployment.helpers import _build_template_env_overrides


TWENTY_ENV_VARS = [
    {
        "key": "PG_DATABASE_URL",
        "value": "postgres://${PG_DATABASE_USER:-twenty}:${PG_DATABASE_PASSWORD:-change_me}@db:5432/${PG_DATABASE_NAME:-twenty}",
        "required": True,
        "sensitive": False,
        "randomizable": False,
        "value_type": "url",
    },
    {
        "key": "POSTGRES_PASSWORD",
        "value": "${PG_DATABASE_PASSWORD:-change_me}",
        "required": True,
        "sensitive": True,
        "randomizable": True,
        "value_type": "password",
    },
    {
        "key": "ENCRYPTION_KEY",
        "value": "${ENCRYPTION_KEY:-change_me}",
        "required": True,
        "sensitive": True,
        "randomizable": True,
        "value_type": "token",
    },
    {
        "key": "APP_SECRET",
        "value": "${APP_SECRET:-}",
        "required": False,
        "sensitive": True,
        "randomizable": True,
        "value_type": "secret",
    },
    {
        "key": "STORAGE_TYPE",
        "value": "${STORAGE_TYPE:-local}",
        "required": False,
        "sensitive": False,
        "randomizable": False,
        "value_type": "text",
    },
]


def test_build_template_env_overrides_generates_referenced_secrets():
    overrides = _build_template_env_overrides(
        {"template_env_vars": TWENTY_ENV_VARS},
        app_name="twenty-crm",
        route_slug="twenty",
        provided_overrides={"SERVER_URL": "https://twenty.example.apps.pluglayer.io"},
    )

    assert overrides["SERVER_URL"] == "https://twenty.example.apps.pluglayer.io"
    assert overrides["PG_DATABASE_PASSWORD"] not in {"", "change_me"}
    assert "${" not in overrides["PG_DATABASE_PASSWORD"]
    assert overrides["ENCRYPTION_KEY"] not in {"", "change_me", "${ENCRYPTION_KEY:-change_me}"}
    assert overrides["APP_SECRET"]
    assert "${" not in overrides["APP_SECRET"]
    assert overrides["STORAGE_TYPE"] == "local"
    assert overrides["PG_DATABASE_USER"] == "twenty"
    assert overrides["PG_DATABASE_NAME"] == "twenty"
    assert "PG_DATABASE_URL" not in overrides
    assert "POSTGRES_PASSWORD" not in overrides
