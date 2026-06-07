from pluglayer_mcp.domain_provider import infer_provider_from_nameservers


def test_infer_provider_cloudflare():
    result = infer_provider_from_nameservers(["ada.ns.cloudflare.com", "tom.ns.cloudflare.com"])
    assert result.provider == "Cloudflare"
    assert result.confidence == "high"


def test_infer_provider_godaddy():
    result = infer_provider_from_nameservers(["ns17.domaincontrol.com", "ns18.domaincontrol.com"])
    assert result.provider == "GoDaddy"


def test_infer_provider_unknown_returns_suggestions():
    result = infer_provider_from_nameservers(["ns1.example.net", "ns2.example.net"])
    assert result.provider is None
    assert result.suggestions
