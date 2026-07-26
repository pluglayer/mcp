import asyncio

from pluglayer_mcp.tools import domains as domain_tools
from pluglayer_mcp.tools.domains import _markdown_dns_table, _provider_ui_host, register_domain_tools


class FakeMCP:
    def __init__(self):
        self.tools = {}

    def tool(self):
        def decorator(func):
            self.tools[func.__name__] = func
            return func

        return decorator


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
        "Cloudflare",
        "hivemindcolony.com",
    )

    assert "`_pluglayer-verify` in Cloudflare (`_pluglayer-verify.hivemindcolony.com` exact DNS name)" in table
    assert "`@` in Cloudflare (`hivemindcolony.com` exact DNS name)" in table


def test_godaddy_apex_never_renders_impossible_cname_record():
    table = _markdown_dns_table(
        {
            "domain": "hivecitadel.com",
            "mode": "single",
            "verification": {
                "name": "_pluglayer-verify.hivecitadel.com",
                "value": "pl-verify-123",
            },
            "dns": {
                "expected_type": "CNAME",
                "expected_value": "cname.apps.pluglayer.io",
            },
        },
        "GoDaddy",
        "hivecitadel.com",
    )

    assert "cannot finish direct DNS routing with GoDaddy" in table
    assert "www.hivecitadel.com" in table
    assert "Permanent (301)" in table
    assert "| CNAME | `@`" not in table


def test_godaddy_subdomain_uses_zone_relative_hosts():
    table = _markdown_dns_table(
        {
            "domain": "www.hivecitadel.com",
            "mode": "single",
            "verification": {
                "name": "_pluglayer-verify.www.hivecitadel.com",
                "value": "pl-verify-123",
            },
            "dns": {
                "expected_type": "CNAME",
                "expected_value": "cname.apps.pluglayer.io",
            },
        },
        "GoDaddy",
        "hivecitadel.com",
    )

    assert "`_pluglayer-verify.www` in GoDaddy" in table
    assert "`www` in GoDaddy (`www.hivecitadel.com` exact DNS name)" in table
    assert "CNAME records only for subdomain prefixes" in table
    assert "routes only the exact hostname `www.hivecitadel.com`" in table
    assert "Permanent (301) Forward only" in table
    assert "https://hivecitadel.com/page-1" in table
    assert "https://www.hivecitadel.com/page-1" in table


def test_root_domain_warns_that_www_needs_separate_routing_or_redirect():
    table = _markdown_dns_table(
        {
            "domain": "example.com",
            "mode": "single",
            "verification": {
                "name": "_pluglayer-verify.example.com",
                "value": "pl-verify-123",
            },
            "dns": {
                "expected_type": "CNAME",
                "expected_value": "cname.apps.pluglayer.io",
            },
        },
        "Cloudflare",
        "example.com",
    )

    assert "routes only the exact hostname `example.com`" in table
    assert "`www.example.com` is not covered automatically" in table
    assert "separate PlugLayer custom domain" in table
    assert "https://www.example.com/page-1" in table


def test_add_custom_domain_blocks_godaddy_apex_before_api_call(monkeypatch):
    def fail_client():
        raise AssertionError("backend must not be called for an impossible GoDaddy apex CNAME")

    monkeypatch.setattr(domain_tools, "_client", fail_client)
    mcp = FakeMCP()
    register_domain_tools(mcp)

    output = asyncio.run(
        mcp.tools["add_custom_domain"](
            "project-1",
            "hivecitadel.com",
            provider_name="GoDaddy",
            dns_zone="hivecitadel.com",
        )
    )

    assert "was not added to PlugLayer" in output
    assert "www.hivecitadel.com" in output
    assert "Permanent (301)" in output


def test_verify_existing_godaddy_apex_returns_recovery_guidance(monkeypatch):
    class FakeClient:
        async def post(self, path):
            assert path == "/v1/plugin/domains/domain-1/verify"
            return {
                "domain": {
                    "id": "domain-1",
                    "domain": "hivecitadel.com",
                    "mode": "single",
                    "status": "waiting_dns",
                    "verification": {},
                    "dns": {"verified": False, "detected": ["76.223.105.230"]},
                }
            }

    monkeypatch.setattr(domain_tools, "_client", lambda: FakeClient())
    mcp = FakeMCP()
    register_domain_tools(mcp)

    output = asyncio.run(
        mcp.tools["verify_custom_domain"](
            "domain-1",
            provider_name="GoDaddy",
            dns_zone="hivecitadel.com",
        )
    )

    assert "already registered" in output
    assert "cannot finish direct DNS routing with GoDaddy" in output
    assert "www.hivecitadel.com" in output
