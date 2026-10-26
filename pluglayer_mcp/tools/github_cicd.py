"""GitHub automatic deployment setup. Authorization stays in the backend."""

import json
from urllib.parse import quote

from pluglayer_mcp.tools.shared import _client, _compact_error


def _path(app_id):
    return f"/v1/plugin/apps/{quote(app_id, safe='')}/github-deployment"


def register_github_cicd_tools(mcp):
    @mcp.tool()
    async def get_github_deployment(app_id: str) -> str:
        """Inspect the repository, branch, workflow and verification state of an app's automatic deployments."""
        try:
            return json.dumps(await _client().get(_path(app_id)), ensure_ascii=False)
        except Exception as exc:
            _compact_error("Could not inspect automatic deployments", exc)

    @mcp.tool()
    async def configure_github_deployment(
        app_id: str, repository: str, repository_id: str, repository_owner_id: str,
        branch: str, workflow_path: str = ".github/workflows/deploy-pluglayer.yml",
        expected_revision: int | None = None,
    ) -> str:
        """Owner-only: allow one exact GitHub repository/branch/workflow to deploy this app automatically.

        Read immutable repository/owner IDs using the user's GitHub access. OAuth
        authorizes setup; no API key is needed. Existing connection changes need
        its current revision. First signed workflow run verifies the connection.
        """
        try:
            result = await _client().put(_path(app_id), {
                "repository": repository, "repository_id": repository_id,
                "repository_owner_id": repository_owner_id, "branch": branch,
                "workflow_path": workflow_path, "expected_revision": expected_revision,
            })
            return json.dumps(result, ensure_ascii=False) + (
                "\nGenerate and publish the workflow, then verify its first deployment. "
                "No PlugLayer API-key secret is required. Connection setup alone does not prove deployment success."
            )
        except Exception as exc:
            _compact_error("Could not configure automatic deployments", exc)

    @mcp.tool()
    async def disconnect_github_deployment(app_id: str, expected_revision: int) -> str:
        """Disable this app's automatic deployments and invalidate its outstanding CI credentials.

        Use the current revision from get_github_deployment. Already accepted
        deployment tasks are not cancelled and the deployed app keeps running.
        """
        try:
            return json.dumps(await _client().post(_path(app_id) + "/disconnect",
                {"expected_revision": expected_revision}), ensure_ascii=False)
        except Exception as exc:
            _compact_error("Could not disconnect automatic deployments", exc)
