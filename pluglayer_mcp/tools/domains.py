"""Custom-domain MCP tools backed by PlugLayer v1 domain APIs."""

from pluglayer_mcp.tools.shared import _client, _compact_error, _status_emoji


def _domain_dns_help(domain: dict) -> str:
    verification = domain.get("verification") or {}
    dns = domain.get("dns") or {}
    txt_name = verification.get("name") or "_pluglayer-verify.example.com"
    txt_value = verification.get("value") or "pl-verify-..."
    expected_type = dns.get("expected_type") or "CNAME"
    expected_value = dns.get("expected_value") or "cname.apps.pluglayer.io"
    domain_name = domain.get("domain") or "example.com"

    dns_lines = [
        "Add these DNS records in your registrar or DNS provider:",
        "",
        f"- TXT",
        f"  Name / Host: `{txt_name}`",
        f"  Content / Value: `{txt_value}`",
        "",
        f"- {expected_type}",
        f"  Name / Host: `{domain_name}`" if expected_type == "CNAME" else f"  Name / Host: `{domain_name}`",
        f"  Target / Value: `{expected_value}`",
        "",
        "Provider wording varies:",
        "- Some providers say `Name` instead of `Host`.",
        "- Some providers say `Content` instead of `Value`.",
        "- CNAME records may use `Target` instead of `Value`.",
        "- Root domains may appear as `@` instead of the full domain.",
        "",
        "After you add the records, tell me `I've added the DNS records` and I can run verification for you.",
    ]
    return "\n".join(dns_lines)


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
    async def add_custom_domain(project_id: str, domain: str, mode: str = "single", app_id: str = "") -> str:
        """Add a custom domain. mode is 'single' or 'wildcard'. The result explains the exact TXT/CNAME fields to enter in DNS."""
        try:
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
                f"{_domain_dns_help(item)}"
            )
        except Exception as e:
            return _compact_error("Error adding domain", e)

    @mcp.tool()
    async def verify_custom_domain(domain_id: str) -> str:
        """Verify the TXT and route DNS records for a custom domain. Use this after the user says the DNS records are added."""
        try:
            data = await _client().post(f"/v1/plugin/domains/{domain_id}/verify")
            domain = data.get("domain", {})
            status = domain.get("status")
            if status == "active":
                extra = "The domain is verified and active."
            elif status == "verified":
                extra = "The domain is verified. If it is attached to an app, PlugLayer should activate routing shortly."
            elif status == "waiting_dns":
                extra = (
                    "The TXT record looks good, but the main route record is still not visible the way PlugLayer expects. "
                    "Double-check the CNAME / target field and whether the DNS provider is flattening or proxying the record."
                )
            else:
                extra = (
                    "PlugLayer still cannot verify the DNS records. Double-check the Name/Host and Content/Value fields exactly as shown."
                )
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
                "If DNS is already verified, PlugLayer will route traffic directly to the app. "
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
    async def remove_custom_domain(domain_id: str) -> str:
        """Remove a custom domain and its Traefik route."""
        try:
            await _client().delete(f"/v1/plugin/domains/{domain_id}")
            return f"Custom domain `{domain_id}` removed."
        except Exception as e:
            return _compact_error("Error removing domain", e)

    @mcp.tool()
    async def update_app_domain(app_id: str, route_slug: str) -> str:
        """Update the app's default PlugLayer route slug. Use this when the user wants to change the built-in pluglayer.io-style app URL; custom domains use the domain tools instead."""
        try:
            data = await _client().patch(f"/v1/plugin/apps/{app_id}", {"route_slug": route_slug})
            app = data.get("app", {})
            task_id = data.get("task_id")
            return (
                f"Default PlugLayer domain updated for **{app.get('name', app_id)}**.\n"
                f"New route slug: `{app.get('route_slug', route_slug)}`\n"
                f"Task ID: `{task_id}`\n"
                "This redeploy can take around 10 minutes. Feel free to keep working and ask me to check status later."
            )
        except Exception as e:
            return _compact_error("Error updating app domain", e)
