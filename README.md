# PlugLayer MCP Server

Deploy and manage your infrastructure through natural language with any MCP-compatible AI assistant.

## Installation

### Option 1: uvx (recommended — no install needed)
```bash
PLUGLAYER_API_KEY=your-pluglayer-api-token uvx pluglayer-mcp
```

This local command mode uses the MCP `stdio` transport by default, which is the right mode for Cursor, Claude Code, and other editor-launched command servers.
The `pluglayer-mcp` command now always uses `stdio` so editor clients cannot accidentally switch it into HTTP mode.

### Option 2: pip
```bash
pip install pluglayer-mcp
PLUGLAYER_API_KEY=your-pluglayer-api-token pluglayer-mcp
```

## Configuration

### Claude Desktop
Add to `~/.config/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "pluglayer": {
      "command": "uvx",
      "type": "stdio",
      "args": ["pluglayer-mcp"],
      "env": {
        "PLUGLAYER_API_KEY": "your-pluglayer-api-token"
      }
    }
  }
}
```

### Cursor
Add to `~/.cursor/mcp.json`:
```json
{
  "pluglayer": {
    "command": "uvx",
    "type": "stdio",
    "args": ["pluglayer-mcp"],
    "env": {
      "PLUGLAYER_API_KEY": "your-pluglayer-api-token"
    }
  }
}
```

### Remote HTTP (hosted)
The remote MCP server runs at `mcp.pluglayer.com`. Pass your token as:
```
Authorization: Bearer your-pluglayer-api-token
```

If you intentionally want to run the package itself as an HTTP MCP server, use:

```bash
pluglayer-mcp-http
```

## Release Checklist

Before publishing a new `pluglayer-mcp` build:

1. Confirm local command mode still uses `stdio` by default.
2. Confirm `PLUGLAYER_API_URL` override works when pointed at a dev API.
3. Confirm package version will be unique for the publish run.
4. Publish from the public repo `main` branch after reviewing the `dev -> main` PR.

After publishing:

1. Restart Cursor, Claude Code, or the MCP client you are testing.
2. If the editor still behaves like an older MCP build, remove and re-add the MCP server entry, then restart the editor.
3. Re-test with a simple command such as:
   - `get_current_user`
   - `list_projects`
   - `get_compute_summary`

## Cursor Notes

- For `command`-based MCP setup, use `uvx pluglayer-mcp`.
- Do not force HTTP transport for local editor usage.
- `pluglayer-mcp` always uses `stdio`, which is the correct transport for Cursor-launched command servers.
- Only use `pluglayer-mcp-http` when you intentionally want to run the package itself as an HTTP MCP server.

## Available Tools

The MCP calls the PlugLayer FastAPI backend instead of re-implementing backend business logic. Auth, roles, ownership, compute guards, and k3s orchestration remain in the backend. MCP and editor plugins should authenticate with a **PlugLayer API token** created in the PlugLayer Settings page, not the browser/session auth token.

Managed registries are configured by PlugLayer admins in the platform UI/API. When `deploy_image` uses mirroring, the backend picks a registry the current user is allowed to use and keeps Kubernetes pull secrets in sync automatically.

| Tool | Description |
|------|-------------|
| `get_current_user` | Show the Authentik-backed user and `roles` |
| `list_projects` | List authenticated user's projects |
| `get_my_projects` | Alias for listing the current user's projects |
| `create_project` | Create a new project namespace |
| `get_project` | Get project details |
| `get_compute_summary` | Show account-level personal + shared compute capacity; estimate first when sizing is still unclear |
| `get_my_available_compute` | Show the current user's available compute capacity; pair with estimate first for planning |
| `get_my_available_computes` | Alias for available compute capacity |
| `estimate_compute` | Estimate required compute, monthly price, and a tailored offer link; preferred before purchase/allocation decisions |
| `list_nodes` | List accessible compute nodes |
| `add_node_ssh` | Add a personal SSH node usable by all of the user's projects |
| `list_registries` | List the registries currently available to the user |
| `deploy_image` | Mirror a Docker image into PlugLayer's managed Docker Hub namespace, then deploy it after backend compute checks |
| `deploy_compose` | Deploy from docker-compose.yml after backend compute checks |
| `list_deployments` | List running apps/deployments |
| `get_apps_by_project` | List apps inside a specific project |
| `get_deployment_status` | Check app status and URL |
| `get_logs` | Get app logs |
| `get_app_logs` | Alias for getting app logs |
| `redeploy` | Redeploy an app |
| `restart_app` | Alias for restarting an app by redeploying it |
| `rollback` | Roll back to previous version |
| `delete_deployment` | Delete an app |
| `list_project_domains` | List custom domains for a project |
| `add_custom_domain` | Add a single or wildcard custom domain and return DNS records |
| `verify_custom_domain` | Verify TXT/CNAME DNS and activate if attached |
| `attach_custom_domain` | Attach a verified custom domain to an app |
| `detach_custom_domain` | Detach a domain while keeping verification |
| `remove_custom_domain` | Remove a domain and its route |
| `get_task_status` | Poll async operation progress |
| `generate_github_actions` | Get CI/CD pipeline YAML |
| `get_cluster_health` | Check cluster status |

## Example Conversations

**Deploy your first app:**
> "I have a FastAPI app at `ghcr.io/myorg/api:latest` that runs on port 8000. Deploy it to my `production` project."

**Convert docker-compose:**
> "Here's my docker-compose.yml: [paste]. Deploy this to PlugLayer."

**Add a node:**
> "Add my server at 192.168.1.100 as personal compute. Here's my SSH key: [paste]"

**CI/CD setup:**
> "Generate a GitHub Actions workflow for my `api` deployment so it auto-deploys on push to main."

**Add a custom domain:**
> "Add `api.example.com` to my production project, show me the DNS records, then verify it and attach it to my API app."

## Getting Your API Key

1. Go to PlugLayer Settings
2. Create a **PlugLayer API token**
3. Copy it once and store it safely
4. Use it as `PLUGLAYER_API_KEY` for MCP, editor plugins, and CI/CD webhook deploys
