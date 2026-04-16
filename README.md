# PlugLayer MCP Server

Deploy and manage your infrastructure through natural language with any MCP-compatible AI assistant.

## Installation

### Option 1: uvx (recommended — no install needed)
```bash
PLUGLAYER_API_KEY=your-token uvx pluglayer-mcp
```

### Option 2: pip
```bash
pip install pluglayer-mcp
PLUGLAYER_API_KEY=your-token pluglayer-mcp
```

## Configuration

### Claude Desktop
Add to `~/.config/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "pluglayer": {
      "command": "uvx",
      "args": ["pluglayer-mcp"],
      "env": {
        "PLUGLAYER_API_KEY": "your-token-from-portal"
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
    "args": ["pluglayer-mcp"],
    "env": {
      "PLUGLAYER_API_KEY": "your-token"
    }
  }
}
```

### Remote HTTP (hosted)
The remote MCP server runs at `mcp.pluglayer.com`. Pass your token as:
```
Authorization: Bearer your-token
```

## Available Tools

The MCP calls the PlugLayer FastAPI backend instead of re-implementing backend business logic. Auth, roles, ownership, compute guards, k3s orchestration, and admin checks remain in the backend.

| Tool | Description |
|------|-------------|
| `get_current_user` | Show the Authentik-backed user and `roles` |
| `list_projects` | List authenticated user's projects |
| `create_project` | Create a new project namespace |
| `get_project` | Get project details |
| `get_compute_summary` | Show account-level personal + shared compute capacity |
| `list_nodes` | List accessible compute nodes |
| `add_node_ssh` | Add a personal SSH node usable by all of the user's projects |
| `deploy_image` | Deploy a Docker image after backend compute checks |
| `deploy_compose` | Deploy from docker-compose.yml after backend compute checks |
| `list_deployments` | List running apps/deployments |
| `get_deployment_status` | Check app status and URL |
| `get_logs` | Get app logs |
| `redeploy` | Redeploy an app |
| `rollback` | Roll back to previous version |
| `delete_deployment` | Delete an app |
| `get_task_status` | Poll async operation progress |
| `admin_get_overview` | Admin-only platform summary |
| `admin_set_compute_defaults` | Admin-only default compute quota metadata |
| `admin_set_node_shared` | Admin-only mark node shared/private |
| `admin_add_shared_ssh_node` | Admin-only add shared PlugLayer SSH compute |
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

## Getting Your API Key

1. Go to [portal.pluglayer.com](https://portal.pluglayer.com)
2. Navigate to Settings
3. Copy your API token
