"""Custom-domain MCP tools backed by PlugLayer v1 domain APIs."""

from pluglayer_mcp.tools.shared import _client, _compact_error, _status_emoji


def _fmt_domain(domain: dict) -> str:
    status = domain.get("status", "unknown")
    app = domain.get("app_id") or "not attached"
    return (
        f"{_status_emoji(status)} **{domain.get('domain')}** (id: `{domain.get('id')}`)\n"
        f"   Status: {status} | Mode: {domain.get('mode')} | App: {app}\n"
        f"   TXT: {domain.get('verification', {}).get('name')} = {domain.get('verification', {}).get('value')}\n"
        f"   DNS: {domain.get('dns', {}).get('expected_type')} -> {domain.get('dns', {}).get('expected_value')}\n"
    )


def register_domain_tools(mcp):
    @mcp.tool()
    async def list_project_domains(project_id: str) -> str:
        """List custom domains for a project."""
        try:
            data = await _client().get(f"/v1/plugin/projects/{project_id}/domains")
            domains = data.get("domains", [])
            if not domains:
                return "No custom domains are configured for this project."
            return "Project domains:\n\n" + "\n".join(_fmt_domain(domain) for domain in domains)
        except Exception as e:
            return _compact_error("Error listing domains", e)

    @mcp.tool()
    async def add_custom_domain(project_id: str, domain: str, mode: str = "single", app_id: str = "") -> str:
        """Add a custom domain. mode is 'single' or 'wildcard'."""
        try:
            data = await _client().post(f"/v1/plugin/projects/{project_id}/domains", {
                "domain": domain,
                "mode": mode,
                "app_id": app_id or None,
            })
            item = data.get("domain", {})
            return "Domain added. Create these DNS records, then run verify_custom_domain():\n\n" + _fmt_domain(item)
        except Exception as e:
            return _compact_error("Error adding domain", e)

    @mcp.tool()
    async def verify_custom_domain(domain_id: str) -> str:
        """Verify TXT/CNAME DNS for a custom domain and activate it if attached."""
        try:
            data = await _client().post(f"/v1/plugin/domains/{domain_id}/verify")
            return _fmt_domain(data.get("domain", {}))
        except Exception as e:
            return _compact_error("Error verifying domain", e)

    @mcp.tool()
    async def attach_custom_domain(domain_id: str, app_id: str, make_primary: bool = False) -> str:
        """Attach a verified custom domain to an app."""
        try:
            data = await _client().post(f"/v1/plugin/domains/{domain_id}/attach", {
                "app_id": app_id,
                "make_primary": make_primary,
            })
            return _fmt_domain(data.get("domain", {}))
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
