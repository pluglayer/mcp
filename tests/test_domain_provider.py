from pluglayer_mcp import domain_provider
from pluglayer_mcp.domain_provider import infer_provider_from_nameservers


def test_infer_provider_cloudflare():
    result = infer_provider_from_nameservers(["ada.ns.cloudflare.com", "tom.ns.cloudflare.com"])
    assert result.provider == "Cloudflare"
    assert result.confidence == "high"


def test_infer_provider_godaddy():
    result = infer_provider_from_nameservers(
        ["ns17.domaincontrol.com", "ns18.domaincontrol.com"],
        zone="hivecitadel.com",
    )
    assert result.provider == "GoDaddy"
    assert result.zone == "hivecitadel.com"


def test_infer_provider_unknown_returns_suggestions():
    result = infer_provider_from_nameservers(["ns1.example.net", "ns2.example.net"])
    assert result.provider is None
    assert result.suggestions


def test_authoritative_zone_lookup_walks_up_from_subdomain(monkeypatch):
    records = {
        "www.hivecitadel.com": [],
        "hivecitadel.com": ["ns17.domaincontrol.com", "ns18.domaincontrol.com"],
    }
    monkeypatch.setattr(domain_provider, "lookup_ns_records", lambda name: records.get(name, []))

    zone, nameservers = domain_provider.lookup_authoritative_nameservers("www.hivecitadel.com")

    assert zone == "hivecitadel.com"
    assert nameservers == ["ns17.domaincontrol.com", "ns18.domaincontrol.com"]
