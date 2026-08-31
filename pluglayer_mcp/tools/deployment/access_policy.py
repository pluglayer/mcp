"""Public app traffic controls; validation and enforcement remain backend-owned."""

import json

from pluglayer_mcp.tools.shared import _client, _compact_error


def _policy_view(app: dict) -> dict:
    policy = app.get("access_policy")
    if not isinstance(policy, dict) or not {
        "http_rate_limit", "tcp_max_connections", "allowed_cidrs"
    }.issubset(policy):
        raise ValueError(
            "Backend did not return a complete access policy. Update the backend; "
            "do not infer defaults or overwrite unknown settings."
        )
    # App detail can include credentials. Never return the full app record here.
    return {
        "app_id": app.get("id"),
        "app_name": app.get("name"),
        "project_id": app.get("project_id"),
        "status": app.get("status"),
        "exposure_type": app.get("exposure_type"),
        "access_policy_protocols": app.get("access_policy_protocols"),
        "access_policy": {key: policy[key] for key in (
            "http_rate_limit", "tcp_max_connections", "allowed_cidrs"
        )},
    }


def register_access_policy_tools(mcp):
    @mcp.tool()
    async def get_app_access_policy(app_id: str) -> str:
        """Read an accessible app's saved IP allowlist, HTTP rate limit, TCP connection cap,
        and exposure without returning environment values. Use with status/logs for
        'check my apps' or 'check my app security'. Saved policy is not a live traffic audit.
        Empty allowed_cidrs allows all source IPs. Missing policy is unknown, not defaults.
        """
        try:
            data = await _client().get(f"/v1/plugin/apps/{app_id}")
            return json.dumps(_policy_view(data.get("app") or {}), indent=2)
        except Exception as exc:
            return _compact_error("Error reading app access policy", exc)

    @mcp.tool()
    async def update_app_access_policy(
        app_id: str,
        confirmed_app_name: str,
        http_average: int,
        http_burst: int,
        http_period_seconds: int,
        tcp_max_connections: int,
        allowed_cidrs: list[str],
    ) -> str:
        """Replace an app's complete ingress policy after authorized remediation or an
        explicit settings request. Read get_app_access_policy first; preserve every
        unchanged value and pass the exact app name from the user's confirmed scope.
        HTTP average is requests per period per peer IP, burst is bucket capacity;
        TCP caps simultaneous connections per route, not requests/sec. Limits are
        local to each route/Traefik instance. CIDRs accept IPv4/IPv6, not URLs/domains;
        [] opens access to all IPs. Never guess trusted clients or turn a public app
        private without approval. Backend enforces permissions, validation and route
        readback; no restart is needed. Re-read policy and check legitimate access
        afterward. On timeout or uncertain enforcement, inspect before retrying.
        """
        try:
            client = _client()
            data = await client.get(f"/v1/plugin/apps/{app_id}")
            app = data.get("app") or {}
            _policy_view(app)  # Fail closed when an older backend omits the policy.
            if not confirmed_app_name or confirmed_app_name != app.get("name"):
                return "Error updating app access policy: exact app name does not match; no changes made."
            result = await client.put(f"/v1/plugin/apps/{app_id}/access", {
                "http_rate_limit": {
                    "average": http_average, "burst": http_burst,
                    "period_seconds": http_period_seconds,
                },
                "tcp_max_connections": tcp_max_connections,
                "allowed_cidrs": allowed_cidrs,
            })
            view = _policy_view(result.get("app") or {})
            view["applied_routes"] = result.get("applied_routes")
            view["verification"] = (
                "Backend save returned. Re-read policy and check intended client access; "
                "zero applied routes does not prove public ingress enforcement."
            )
            return json.dumps(view, indent=2)
        except Exception as exc:
            return _compact_error(
                "Error updating app access policy; inspect current state before retrying", exc
            )
