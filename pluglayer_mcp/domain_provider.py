"""Detect likely DNS/domain provider from public DNS metadata."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import urlencode
from urllib.request import urlopen


_PROVIDER_PATTERNS: dict[str, tuple[str, ...]] = {
    "Cloudflare": ("cloudflare.com",),
    "AWS Route 53": ("awsdns-", "route53", "awsdns"),
    "GoDaddy": ("domaincontrol.com",),
    "Namecheap": ("registrar-servers.com",),
    "Squarespace": ("squarespacedns.com",),
    "Google Cloud DNS": ("googledomains.com", "google.com"),
    "Wix": ("wixdns.net",),
    "Bluehost": ("bluehost.com",),
    "DigitalOcean": ("digitalocean.com",),
    "Vercel DNS": ("vercel-dns.com",),
    "Azure DNS": ("azure-dns.com", "azure-dns.net", "azure-dns.org", "azure-dns.info"),
}


@dataclass
class DomainProviderDetection:
    provider: str | None
    confidence: str
    source: str
    zone: str | None
    nameservers: list[str]
    suggestions: list[str]


def infer_provider_from_nameservers(
    nameservers: Iterable[str],
    *,
    zone: str | None = None,
) -> DomainProviderDetection:
    normalized = [item.strip().lower().rstrip(".") for item in nameservers if item]
    for provider, patterns in _PROVIDER_PATTERNS.items():
        for record in normalized:
            if any(pattern in record for pattern in patterns):
                return DomainProviderDetection(
                    provider=provider,
                    confidence="high",
                    source="ns",
                    zone=zone,
                    nameservers=normalized,
                    suggestions=[],
                )
    return DomainProviderDetection(
        provider=None,
        confidence="unknown",
        source="ns",
        zone=zone,
        nameservers=normalized,
        suggestions=list(_PROVIDER_PATTERNS.keys())[:8],
    )


def lookup_ns_records(domain: str) -> list[str]:
    url = "https://dns.google/resolve?" + urlencode({"name": domain, "type": "NS"})
    with urlopen(url, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
    answers = payload.get("Answer") or []
    return [
        str(item.get("data", "")).rstrip(".")
        for item in answers
        if item.get("type") == 2 and item.get("data")
    ]


def lookup_authoritative_nameservers(domain: str) -> tuple[str | None, list[str]]:
    """Find the closest DNS zone so subdomain records get the right UI host label."""
    normalized = domain.strip().lower().rstrip(".")
    if normalized.startswith("*."):
        normalized = normalized[2:]
    labels = [label for label in normalized.split(".") if label]
    for index in range(max(0, len(labels) - 1)):
        candidate = ".".join(labels[index:])
        nameservers = lookup_ns_records(candidate)
        if nameservers:
            return candidate, nameservers
    return None, []


def detect_domain_provider(domain: str) -> DomainProviderDetection:
    try:
        zone, nameservers = lookup_authoritative_nameservers(domain)
    except Exception:
        zone = None
        nameservers = []
    return infer_provider_from_nameservers(nameservers, zone=zone)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Detect likely domain DNS provider from NS records.")
    parser.add_argument("domain", help="Domain to inspect")
    args = parser.parse_args()
    result = detect_domain_provider(args.domain)
    print(
        json.dumps(
            {
                "provider": result.provider,
                "confidence": result.confidence,
                "source": result.source,
                "zone": result.zone,
                "nameservers": result.nameservers,
                "suggestions": result.suggestions,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
