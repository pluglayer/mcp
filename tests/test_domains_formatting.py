from pluglayer_mcp.tools.domains import _markdown_dns_table, _provider_ui_host


def test_provider_ui_host_uses_relative_labels_for_godaddy():
    assert _provider_ui_host("hivemindcolony.com", "hivemindcolony.com", "GoDaddy") == "@"
    assert _provider_ui_host("_pluglayer-verify.hivemindcolony.com", "hivemindcolony.com", "GoDaddy") == "_pluglayer-verify"
    assert _provider_ui_host("www.hivemindcolony.com", "hivemindcolony.com", "GoDaddy") == "www"


def test_provider_ui_host_keeps_fqdn_for_google_cloud_dns():
    assert _provider_ui_host("hivemindcolony.com", "hivemindcolony.com", "Google Cloud DNS") == "hivemindcolony.com"


def test_markdown_dns_table_shows_provider_host_and_exact_dns_name():
    table = _markdown_dns_table(
        {
            "domain": "hivemindcolony.com",
            "verification": {
                "name": "_pluglayer-verify.hivemindcolony.com",
                "value": "pl-verify-123",
            },
            "dns": {
                "expected_type": "CNAME",
                "expected_value": "cname.apps.pluglayer.io",
            },
        },
        "GoDaddy",
    )

    assert "`_pluglayer-verify` in GoDaddy (`_pluglayer-verify.hivemindcolony.com` exact DNS name)" in table
    assert "`@` in GoDaddy (`hivemindcolony.com` exact DNS name)" in table
