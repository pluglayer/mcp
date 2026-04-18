"""Cicd Health MCP tools."""

from pluglayer_mcp.tools.shared import _client, _compact_error


def register_cicd_health_tools(mcp):
    @mcp.tool()
    async def generate_github_actions(project_id: str, deployment_id: str, github_org: str = "your-org") -> str:
        """Generate a GitHub Actions workflow YAML for PlugLayer CI/CD."""
        try:
            data = await _client().get("/v1/cicd/generate/github-actions", params={
                "project_id": project_id,
                "deployment_id": deployment_id,
                "repo": github_org,
            })
            workflow = data.get("workflow_yaml", "")
            filename = data.get("filename", ".github/workflows/deploy-pluglayer.yml")
            return (
                f"📋 **GitHub Actions Workflow**\n"
                f"Save as: `{filename}`\n\n"
                f"```yaml\n{workflow}\n```\n\n"
                "Setup steps:\n"
                "1. Create this file in your repo.\n"
                "2. Add `PLUGLAYER_API_KEY` as a GitHub secret.\n"
                "3. Push to main/master to trigger deploys."
            )
        except Exception as e:
            return _compact_error("Error generating pipeline", e)

    @mcp.tool()
    async def get_cluster_health() -> str:
        """Check PlugLayer API and k3s cluster health."""
        try:
            health = await _client().get("/v1/health")
            k3s = await _client().get("/v1/health/k3s")
            return (
                "🩺 **PlugLayer Health**\n"
                f"API: {health.get('status', 'unknown')}\n"
                f"k3s: {'healthy' if k3s.get('ok') else 'unavailable'} — {k3s.get('message', '')}"
            )
        except Exception as e:
            return _compact_error("Error checking health", e)
