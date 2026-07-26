"""Custom-domain MCP tools backed by PlugLayer v1 domain APIs."""

from pluglayer_mcp.domain_provider import DomainProviderDetection, detect_domain_provider
from pluglayer_mcp.tools.shared import _client, _compact_error, _status_emoji


def _normalize_dns_name(value: str) -> str:
    return value.strip().rstrip(".").lower()


def _provider_uses_relative_hosts(provider_name: str | None) -> bool:
    provider = _normalize_dns_name(provider_name or "")
    return provider in {"cloudflare", "godaddy", "namecheap", "squarespace"}


def _is_godaddy(provider_name: str | None) -> bool:
    return _normalize_dns_name(provider_name or "").replace(" ", "").startswith("godaddy")


def _provider_root_token(provider_name: str | None) -> str | None:
    provider = _normalize_dns_name(provider_name or "")
    if provider in {"cloudflare", "godaddy", "namecheap", "squarespace"}:
        return "@"
    return None


def _provider_ui_host(record_name: str, zone_name: str | None, provider_name: str | None) -> str:
    record = _normalize_dns_name(record_name)
    zone = _normalize_dns_name(zone_name or "")
    if not record or not zone:
        return record_name
    if not _provider_uses_relative_hosts(provider_name):
        return record_name
    if record == zone:
        return _provider_root_token(provider_name) or record_name
    suffix = f".{zone}"
    if record.endswith(suffix):
        return record[: -len(suffix)]
    return record_name


def _provider_host_display(record_name: str, zone_name: str | None, provider_name: str | None) -> str:
    exact_name = record_name.strip().rstrip(".")
    if not provider_name:
        return f"`{exact_name}`"
    ui_name = _provider_ui_host(record_name, zone_name, provider_name).strip()
    if ui_name == exact_name:
        return f"`{exact_name}`"
    provider = provider_name.strip()
    return f"`{ui_name}` in {provider} (`{exact_name}` exact DNS name)"


def _provider_notes(provider_name: str | None) -> list[str]:
    provider = (provider_name or "").strip().lower()
    notes = {
        "cloudflare": [
            "Turn off proxying for the first verification pass if PlugLayer cannot see the route record yet.",
            "Cloudflare may show the root record as `@` instead of the full domain.",
        ],
        "godaddy": [
            "GoDaddy accepts CNAME records only for subdomain prefixes such as `www`; its CNAME Name field cannot be `@`.",
            "In GoDaddy's Name field, use only the zone-relative label shown in the table.",
            "Use the exact TXT host shown by PlugLayer; do not paste the TXT value into the host field.",
        ],
        "namecheap": [
            "In Namecheap's Host field, use `@` for the root domain and only the left-hand label such as `www` or `_pluglayer-verify` for subdomains.",
            "Keep TTL on automatic/default unless you have a specific reason to change it.",
        ],
        "squarespace": [
            "Squarespace DNS may take a little longer to surface TXT changes than some providers.",
            "Squarespace often wants only the Host label, so use `@` for root or a short label like `_pluglayer-verify` or `www`.",
        ],
        "google cloud dns": [
            "Google DNS accepts fully qualified names cleanly; trailing dots are okay but not required in most UIs.",
            "Make sure you are editing the authoritative zone for this exact domain.",
        ],
    }
    return notes.get(provider, ["Double-check whether the provider expects `@` for the root record."])


def _route_record_name(domain: dict) -> str:
    domain_name = domain.get("domain") or "example.com"
    return f"*.{domain_name}" if domain.get("mode") == "wildcard" else domain_name


def _is_apex_record(record_name: str, dns_zone: str | None) -> bool:
    return bool(dns_zone and _normalize_dns_name(record_name) == _normalize_dns_name(dns_zone))


def _godaddy_apex_guidance(domain_name: str, dns_zone: str, *, existing: bool = False) -> str:
    prefix = (
        f"**{domain_name} is already registered, but it cannot finish direct DNS routing with GoDaddy DNS.**"
        if existing
        else f"**{domain_name} was not added to PlugLayer.**"
    )
    www_name = f"www.{dns_zone}"
    return "\n".join(
        [
            prefix,
            "",
            "GoDaddy does not allow a CNAME whose Name is `@`, and PlugLayer's route target is a hostname rather than a stable A-record IP. Do not replace the parking A record with a guessed or copied IP.",
            "",
            "Recommended supported setup:",
            f"1. Add `{www_name}` to PlugLayer instead, using DNS zone `{dns_zone}`.",
            f"2. In GoDaddy DNS, add `CNAME` with Name `www` and Target `cname.apps.pluglayer.io`.",
            f"3. In GoDaddy, open **DNS → Forwarding → Add Forwarding**, choose **Domain**, set the destination to `https://{www_name}`, and choose **Permanent (301)** with **Forward only** (no masking).",
            "",
            f"The apex redirect remains managed by GoDaddy; `{www_name}` is the custom hostname routed directly by PlugLayer.",
            "",
            "GoDaddy forwarding guide: https://www.godaddy.com/help/forward-my-godaddy-domain-12123",
        ]
    )


def _provider_context(
    domain_name: str,
    provider_name: str | None,
    dns_zone: str | None,
) -> tuple[str | None, str | None, DomainProviderDetection | None]:
    provider = provider_name.strip() if provider_name else None
    zone = _normalize_dns_name(dns_zone or "") or None
    detection = None
    if not provider or not zone:
        detection = detect_domain_provider(domain_name)
        provider = provider or detection.provider
        zone = zone or detection.zone
    return provider, zone, detection


def _markdown_dns_table(
    domain: dict,
    provider_name: str | None = None,
    dns_zone: str | None = None,
) -> str:
    verification = domain.get("verification") or {}
    dns = domain.get("dns") or {}
    txt_name = verification.get("name") or "_pluglayer-verify.example.com"
    txt_value = verification.get("value") or "pl-verify-..."
    expected_type = dns.get("expected_type") or "CNAME"
    expected_value = dns.get("expected_value") or "cname.apps.pluglayer.io"
    domain_name = domain.get("domain") or "example.com"
    route_name = _route_record_name(domain)
    if _is_godaddy(provider_name) and _is_apex_record(route_name, dns_zone):
        return _godaddy_apex_guidance(domain_name, dns_zone or domain_name, existing=True)
    records = [
        ("TXT", txt_name, txt_value, "Ownership verification"),
        (expected_type, route_name, expected_value, "Traffic routing to your app"),
    ]
    lines = [
        "| Type | Name / Host | Content / Value / Target | Description |",
        "| --- | --- | --- | --- |",
    ]
    lines.extend(
        f"| {rtype} | {_provider_host_display(name, dns_zone, provider_name)} | `{value}` | {desc or '-'} |"
        for rtype, name, value, desc in records
    )
    if provider_name:
        lines.append(f"\nDetected provider: **{provider_name}**")
        for note in _provider_notes(provider_name):
            lines.append(f"- {note}")
    else:
        lines.append("\nProvider not confirmed yet.")
        lines.append("- Confirm the DNS provider and authoritative zone before converting exact names into relative Host/Name labels.")
    lines.append("\nAfter you add the records, tell me you've added them and I can verify and continue.")
    return "\n".join(lines)


def _fmt_domain(domain: dict) -> str:
    status = domain.get("status", "unknown")
    app = domain.get("app_id") or "not attached"
    verified = (domain.get("dns") or {}).get("verified")
    detected = (domain.get("dns") or {}).get("detected") or []
    lines = [
        f"{_status_emoji(status)} **{domain.get('domain')}** (id: `{domain.get('id')}`)",
        f"Status: {status}",
        f"Mode: {domain.get('mode')}",
        f"Attached app: {app}",
        f"DNS route visible: {'yes' if verified else 'no'}",
    ]
    if detected:
        lines.append(f"Detected DNS values: {', '.join(str(item) for item in detected)}")
    return "\n".join(lines)


def register_domain_tools(mcp):
    @mcp.tool()
    async def list_project_domains(project_id: str) -> str:
        """List custom domains for a project and show their verification state."""
        try:
            data = await _client().get(f"/v1/plugin/projects/{project_id}/domains")
            domains = data.get("domains", [])
            if not domains:
                return "No custom domains are configured for this project yet."
            return "Project domains:\n\n" + "\n\n".join(_fmt_domain(domain) for domain in domains)
        except Exception as e:
            return _compact_error("Error listing domains", e)

    @mcp.tool()
    async def get_domains_by_project(project_id: str) -> str:
        """Alias for list_project_domains() using project-first wording. Use this before asking the user which domain they want so existing project domains can be offered as options."""
        return await list_project_domains(project_id)

    @mcp.tool()
    async def detect_custom_domain_provider(domain: str) -> str:
        """Detect the likely DNS/domain provider for a custom domain from public NS records so the agent can confirm it with the user before showing tailored DNS steps."""
        try:
            result = detect_domain_provider(domain)
            if result.provider:
                lines = [
                    f"Likely DNS provider for **{domain}**: **{result.provider}**",
                    f"Confidence: {result.confidence}",
                ]
                if result.nameservers:
                    lines.append(f"Nameservers: {', '.join(result.nameservers)}")
                if result.zone:
                    lines.append(f"Authoritative DNS zone: **{result.zone}**")
                lines.append("Please confirm this provider with the user before giving final DNS click-by-click instructions.")
                return "\n".join(lines)
            options = ", ".join(result.suggestions) if result.suggestions else "Cloudflare, GoDaddy, Namecheap, Squarespace"
            return (
                f"I could not confidently detect the DNS provider for **{domain}**.\n"
                f"Offer the user these options: {options}, or let them write their own provider name.\n"
                "Once they confirm the provider, show the DNS record table tailored to that provider."
            )
        except Exception as e:
            return _compact_error("Error detecting domain provider", e)

    @mcp.tool()
    async def add_custom_domain(
        project_id: str,
        domain: str,
        mode: str = "single",
        app_id: str = "",
        provider_name: str = "",
        dns_zone: str = "",
    ) -> str:
        """Add a custom domain after provider detection. Pass the confirmed provider_name and authoritative dns_zone. GoDaddy apex domains are rejected before API creation because GoDaddy cannot publish CNAME @; use www plus apex forwarding."""
        try:
            provider, zone, _ = _provider_context(domain, provider_name, dns_zone)
            route_name = f"*.{domain}" if mode == "wildcard" else domain
            if _is_godaddy(provider):
                if not zone:
                    return (
                        "Custom domain not added: PlugLayer could not confirm the authoritative DNS zone, "
                        "so it cannot safely tell whether GoDaddy would reject the route as an apex CNAME. "
                        "Run detect_custom_domain_provider first, then retry with its authoritative zone in `dns_zone`."
                    )
                if _is_apex_record(route_name, zone):
                    return _godaddy_apex_guidance(domain, zone)
            data = await _client().post(
                f"/v1/plugin/projects/{project_id}/domains",
                {
                    "domain": domain,
                    "mode": mode,
                    "app_id": app_id or None,
                },
            )
            item = data.get("domain", {})
            return (
                "Custom domain added.\n\n"
                f"{_fmt_domain(item)}\n\n"
                f"{_markdown_dns_table(item, provider, zone)}"
            )
        except Exception as e:
            return _compact_error("Error adding domain", e)

    @mcp.tool()
    async def verify_custom_domain(domain_id: str, provider_name: str = "", dns_zone: str = "") -> str:
        """Verify a custom domain after DNS is added. Pass provider_name and dns_zone so an existing GoDaddy apex record gets actionable www + forwarding recovery guidance."""
        try:
            data = await _client().post(f"/v1/plugin/domains/{domain_id}/verify")
            domain = data.get("domain", {})
            status = domain.get("status")
            if status == "active":
                extra = "The domain is verified and active."
            elif status == "verified":
                extra = "The domain is verified. If it is attached to an app, routing should activate shortly."
            elif status == "waiting_dns":
                provider, zone, _ = _provider_context(domain.get("domain", ""), provider_name, dns_zone)
                if _is_godaddy(provider) and _is_apex_record(_route_record_name(domain), zone):
                    extra = _godaddy_apex_guidance(domain.get("domain", ""), zone or "", existing=True)
                else:
                    extra = (
                        "The TXT record looks good, but the traffic record is still not visible the way PlugLayer expects. "
                        "Double-check the Name / Host and Content / Value / Target fields exactly."
                    )
            else:
                extra = "PlugLayer still cannot verify the DNS records. Recheck the table values and provider-specific notes."
            return f"{_fmt_domain(domain)}\n\n{extra}"
        except Exception as e:
            return _compact_error("Error verifying domain", e)

    @mcp.tool()
    async def attach_custom_domain(domain_id: str, app_id: str, make_primary: bool = False) -> str:
        """Attach a verified custom domain to an app. Set make_primary=true if you want it to become the app's main URL."""
        try:
            data = await _client().post(
                f"/v1/plugin/domains/{domain_id}/attach",
                {
                    "app_id": app_id,
                    "make_primary": make_primary,
                },
            )
            return (
                f"{_fmt_domain(data.get('domain', {}))}\n\n"
                "If DNS is already verified, traffic will route directly to the user's deployed app. "
                "If not, add the DNS records first and then run verify_custom_domain()."
            )
        except Exception as e:
            return _compact_error("Error attaching domain", e)

    @mcp.tool()
    async def detach_custom_domain(domain_id: str) -> str:
        """Detach a custom domain from its app while keeping verification."""
        try:
            data = await _client().post(f"/v1/plugin/domains/{domain_id}/detach")
            return _fmt_domain(data.get("domain", {}))
        except Exception as e:
            return _compact_error("Error detaching domain", e)

    @mcp.tool()
    async def update_app_domain(app_id: str, route_slug: str) -> str:
        """Update the app's default pluglayer.io route slug. Use this when the user chooses the built-in subdomain now and may switch to a custom domain later."""
        try:
            data = await _client().patch(f"/v1/plugin/apps/{app_id}", {"route_slug": route_slug})
            app = data.get("app", {})
            task_id = data.get("task_id")
            return (
                f"Default app subdomain updated for **{app.get('name', app_id)}**.\n"
                f"New route slug: `{app.get('route_slug', route_slug)}`\n"
                f"Task ID: `{task_id}`\n"
                "This redeploy can take around 10 minutes. Feel free to keep working and ask me to check status later."
            )
        except Exception as e:
            return _compact_error("Error updating app domain", e)
