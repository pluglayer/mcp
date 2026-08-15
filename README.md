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

For editor installations, PlugLayer also reads
`~/.pluglayer/credentials.env` on every tool call. Saving or rotating
`PLUGLAYER_API_KEY` (and optionally `PLUGLAYER_API_URL`) there takes effect on
the next call without restarting the server. A client's OAuth or generic
`mcp_auth` action does not configure credentials for a local `stdio` server.

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
  "mcpServers": {
    "pluglayer": {
      "command": "uvx",
      "type": "stdio",
      "args": ["pluglayer-mcp@latest"],
      "env": {
        "PLUGLAYER_API_KEY": "your-pluglayer-api-token"
      }
    }
  }
}
```

Use either this manual registration or the PlugLayer Cursor plugin's bundled
server, not both. If both appear in Cursor's Tools & MCP settings, disable or
remove the manual copy so tool calls cannot land on servers with different
authentication state.

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
3. Let the publish workflow stamp the package version from the UTC date/time,
   unique GitHub run ID, and run-attempt number. Do not reuse a published PyPI
   version or artifact filename.
4. Publish from the public repo `main` branch after reviewing the `dev -> main` PR.

After publishing:

1. Restart Cursor, Claude Code, or the MCP client you are testing.
2. If the editor still behaves like an older MCP build, remove and re-add the MCP server entry, then restart the editor.
3. Re-test with a simple command such as:
   - `get_current_user`
   - `list_projects`
   - `get_compute_summary`
   - `list_my_feedback`

## Cursor Notes

- For `command`-based MCP setup, use `uvx pluglayer-mcp`.
- Do not force HTTP transport for local editor usage.
- `pluglayer-mcp` always uses `stdio`, which is the correct transport for Cursor-launched command servers.
- Only use `pluglayer-mcp-http` when you intentionally want to run the package itself as an HTTP MCP server.

## Available Tools

The MCP calls the PlugLayer FastAPI backend instead of re-implementing backend business logic. Auth, roles, ownership, compute guards, and k3s orchestration remain in the backend. MCP and editor plugins should authenticate with a **PlugLayer API token** created in the PlugLayer Settings page, not the browser/session auth token.

Managed registries are configured by PlugLayer admins in the platform UI/API. When `deploy_image` uses mirroring, the backend picks a registry the current user is allowed to use and keeps Kubernetes pull secrets in sync automatically.

Databases are a first-class **Data Layer** workflow in MCP. When a user needs a new database, wants to know whether one already exists, asks for a connection string, or needs env vars to wire an app to a database, the preferred MCP path is:

1. `list_user_databases`
2. if needed, `list_database_templates`
3. `check_slug_availability`
4. optionally `check_database_slug_availability`
5. `create_database`
   - the MCP tool resolves required deploy-time database env vars itself
   - password/secret/token/key fields are generated there when the template expects a random value
   - database-name placeholders are filled from the chosen app name
6. `get_task_status`
7. `get_database_connection_details`
8. optionally `get_database_logs` when troubleshooting
9. use `update_database_access`, `restart_database`, or `remove_database` for follow-up lifecycle actions

After provisioning a database, the assistant should proactively suggest or apply exact env var updates for dependent apps instead of leaving the user with only a raw connection string.

Marketplace template deployment through MCP now supports both:

1. deploying into an existing project by `project_id`
2. creating a new project inline by passing `project_name`

| Tool | Description |
|------|-------------|
| `get_current_user` | Show the Authentik-backed user and `roles` |
| `get_user_context` | Load the caller's stored user memory/context |
| `update_user_context` | Update the caller's stored user memory/context |
| `submit_feedback` | Submit authenticated, redacted product feedback with optional affected-tool, expected/actual behavior, error, and page context |
| `list_my_feedback` | List the authenticated user's feedback tickets and statuses |
| `get_feedback` | Inspect one feedback ticket and its current resolution note |
| `list_projects` | List authenticated user's projects |
| `get_my_projects` | Alias for listing the current user's projects |
| `create_project` | Create a new project namespace |
| `rename_project` | Rename a project's display name without changing its slug, namespace, or existing app URLs |
| `get_project` | Get project details, current apps in the project, and attached custom-domain state |
| `remove_project` | Remove one of the user's projects by deleting its apps first, requesting namespace cleanup, and then archiving the project record/history |
| `delete_project` | Alias for `remove_project` |
| `get_compute_summary` | Show account-level capacity, or pass `project_id` for attached-node recorded allocation plus live scheduler headroom; estimate first when sizing is unclear |
| `get_my_available_compute` | Show the current user's available compute capacity; pair with estimate first for planning |
| `get_my_available_computes` | Alias for available compute capacity |
| `estimate_compute` | Estimate required compute, monthly price, and a tailored offer link; preferred before purchase/allocation decisions |
| `list_nodes` | List accessible compute nodes |
| `list_attachable_project_nodes` | List owner-held dedicated nodes and their project attachment state |
| `attach_node_to_project` | Attach an available dedicated node to one project (owner-only, idempotent) |
| `detach_node_from_project` | Detach an unused dedicated node after explicit confirmation; active apps block it |
| `list_registries` | List the registries currently available to the user |
| `deploy_image` | Mirror a Docker image into PlugLayer's managed Docker Hub namespace, then deploy it after backend compute checks; if a similar app already exists and the namespace is full, use update/replace flow instead of a brand-new app |
| `upload_image_archive_and_deploy` | Upload a locally built Docker or OCI tar archive from the user's machine; if the target app already exists, switch to the app upload-first redeploy flow, otherwise create and deploy a new app |
| `upload_image_archive_and_redeploy_app` | Upload a newly rebuilt Docker or OCI tar archive for an existing app, push it with a new tag, keep the slug unchanged, and queue that app's redeploy |
| `deploy_compose` | Analyze docker-compose.yml, split it into separate deploy units, route known databases through Data Layer templates, deploy remaining services as separate apps, and require uploaded archives for local-build services |
| `analyze_compose_deploy_plan` | Preview how PlugLayer will split a docker-compose stack into Data Layer databases, separate compose apps, and local-build image services |
| `get_compose_local_build_commands` | Generate exact `docker buildx`, smoke-test, and OCI export commands for local-build compose services before they are uploaded and deployed |
| `list_deployments` | List running apps/deployments |
| `get_apps_by_project` | List apps inside a specific project; use this before deploy when you need to clarify update vs replace vs separate new app, especially when a full namespace should block duplicate new-app deploys |
| `check_slug_availability` | Check whether a PlugLayer slug is free inside a project before deploy or rename |
| `get_deployment_status` | Check app status and URL |
| `get_logs` | Get app logs |
| `get_app_logs` | Alias for getting app logs |
| `get_app_connection_env_vars` | Get concrete connection env vars and connection strings for an app/database so dependent apps can be updated correctly |
| `apply_app_env_vars` | Securely import arbitrary runtime env vars from dotenv/`KEY=VALUE`, JSON, YAML text, or a direct key/value object; merge or replace, then optionally restart/redeploy without returning values |
| `list_marketplace_templates` | List deployable marketplace templates before choosing one for a project |
| `get_marketplace_template` | Inspect one marketplace template, including its required env vars |
| `deploy_marketplace_template` | Deploy a marketplace template into an existing project or create a new project inline during the same MCP flow |
| `exec_app_terminal` | Execute a command in the caller's own deployed app container with a fixed 360-second timeout; keep terminal input at or below 10,000 characters and about 350 lines |
| `redeploy` | Redeploy an app after confirming the exact app name; the existing slug stays unchanged |
| `restart_app` | Alias for restarting an app by redeploying it |
| `rollback` | Roll back to previous version |
| `remove_app` | Remove one of the user's apps, tear down its runtime workload, revoke active routing, and mark it as removed |
| `delete_app` | Alias for `remove_app` |
| `delete_deployment` | Alias for `remove_app` |
| `list_database_templates` | List ready-to-deploy database templates |
| `list_user_databases` | List the caller's provisioned databases, optionally by project |
| `check_database_slug_availability` | Check whether a Data Layer slug is free in a project before provisioning or renaming a database |
| `create_database` | Provision a database from a template after backend compute and project checks, resolving password-like env vars inside the MCP flow first |
| `get_database_connection_details` | Get connection strings, env vars, and docs for a provisioned database |
| `sync_database_env_to_app` | Patch one app's env vars from a provisioned database's concrete connection fields, then restart the existing app |
| `get_database_logs` | Read logs from a provisioned database app |
| `update_database_access` | Update the public TCP IP allowlist for a provisioned database |
| `restart_database` | Restart a provisioned database by queueing its restart flow |
| `remove_database` | Remove a provisioned database and tear down its runtime workload/routing |
| `delete_database` | Alias for `remove_database` |
| `list_project_domains` | List custom domains for a project |
| `get_domains_by_project` | Alias for project-domain lookup; use this before asking which domain the user wants so existing project domains can be offered as options |
| `detect_custom_domain_provider` | Detect the likely DNS provider and authoritative zone so the user can confirm them before DNS instructions are shown |
| `add_custom_domain` | Add a single or wildcard custom domain and return provider-friendly DNS records; explains that root and `www` need separate routing or an explicit redirect, and rejects GoDaddy apex CNAME attempts with a supported `www` + 301 forwarding path |
| `verify_custom_domain` | Verify TXT/CNAME DNS and activate if attached |
| `attach_custom_domain` | Attach a verified custom domain to an app |
| `detach_custom_domain` | Detach a domain while keeping verification |
| `get_task_status` | Poll async operation progress |
| `inspect_local_github_repo` | Check whether the local repo has git plus a GitHub `origin` configured |
| `generate_github_actions` | Get GitHub Actions YAML for a 3-step PlugLayer CI/CD flow: build OCI image, upload it to the same app id, then merge env vars and restart/redeploy |

## Example Conversations

**Deploy your first app:**
> "I have a FastAPI app at `ghcr.io/myorg/api:latest` that runs on port 8000. Deploy it into my `production` project in my cloud."

**Convert docker-compose:**
> "Here's my docker-compose.yml: [paste]. Deploy this to PlugLayer."

**CI/CD setup:**
> "Generate a GitHub Actions workflow for my `api` app so every push rebuilds it, uploads it to PlugLayer, and redeploys the same app id."

The generated workflow expects:
- public reusable actions from `pluglayer/actions`
- required secrets:
  - `PLUGLAYER_API_KEY`
- optional secrets:
  - `PLUGLAYER_API_URL` (defaults to `https://api.pluglayer.com`)
  - `PLUGLAYER_BUILD_ENV_JSON` (JSON object of build-time env vars/build args to inject during image build)
  - `PLUGLAYER_ENV_JSON` (JSON object of runtime env vars securely imported before the final restart)

**Add a custom domain:**
> "Add `api.example.com` to my production project, detect the provider, show me the DNS records in a table, then verify it and attach it to my API app."

For a root/`www` website pair, say whether both hostnames must work. PlugLayer routes
exact hostnames, so `example.com` is not automatically covered when only
`www.example.com` is attached. Configure the root separately or redirect it to
`www`, then test a nested path such as `/page-1` on both names.

**Provision a database and wire the backend to it:**
> "Create a Postgres database in my `marketplace` project, check whether the slug `postgres` is available first, and after it finishes show me the connection env vars so we can update my backend."

**Reuse an existing database instead of creating a new one:**
> "Check whether I already have a Mongo or Postgres database in my project. If I do, show me the connection details and suggest the backend env vars I should update."

## Getting Your API Key

1. Go to PlugLayer Settings
2. Create a **PlugLayer API token**
3. Copy it once and store it safely
4. Use it as `PLUGLAYER_API_KEY` for MCP, editor plugins, and the 3-step CI/CD actions flow
