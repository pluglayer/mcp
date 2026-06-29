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
    nameservers: list[str]
    suggestions: list[str]


def infer_provider_from_nameservers(nameservers: Iterable[str]) -> DomainProviderDetection:
    normalized = [item.strip().lower().rstrip(".") for item in nameservers if item]
    for provider, patterns in _PROVIDER_PATTERNS.items():
        for record in normalized:
            if any(pattern in record for pattern in patterns):
                return DomainProviderDetection(
                    provider=provider,
                    confidence="high",
                    source="ns",
                    nameservers=normalized,
                    suggestions=[],
                )
    return DomainProviderDetection(
        provider=None,
        confidence="unknown",
        source="ns",
        nameservers=normalized,
        suggestions=list(_PROVIDER_PATTERNS.keys())[:8],
    )


def lookup_ns_records(domain: str) -> list[str]:
    url = "https://dns.google/resolve?" + urlencode({"name": domain, "type": "NS"})
    with urlopen(url, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
    answers = payload.get("Answer") or []
    return [str(item.get("data", "")).rstrip(".") for item in answers if item.get("data")]


def detect_domain_provider(domain: str) -> DomainProviderDetection:
    try:
        nameservers = lookup_ns_records(domain)
    except Exception:
        nameservers = []
    return infer_provider_from_nameservers(nameservers)


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
                "nameservers": result.nameservers,
                "suggestions": result.suggestions,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
