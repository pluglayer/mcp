# Contributing to PlugLayer MCP

This repository exposes PlugLayer's end-user MCP server. Contributions should improve the end-user deployment experience, reliability, documentation, and safe integrations.

## Step-by-step contribution flow

1. Star the repository if you want to follow updates.
2. Open an issue first if the change is large, changes tool behavior, or needs design discussion.
3. Fork the repository to your own GitHub account.
4. Clone your fork locally.
5. Create a feature branch from your fork's `dev` branch if it exists. If not, create the branch from `main`.
6. Make one focused change at a time.
7. Run the local validation steps before pushing.
8. Push your branch to your fork.
9. Open a pull request from your fork branch into the public `dev` branch.
10. Respond to review feedback and update the same branch.
11. After maintainers review and merge, the change can be promoted through the normal maintainer flow into `main`.

## Before you start

- Read `README.md` first.
- Prefer small pull requests with one clear purpose.
- Open an issue or discussion first for larger changes, new tool surfaces, or behavior changes that affect existing MCP clients.

## What belongs here

- MCP tool improvements for end users
- Better documentation and examples
- Safer defaults
- Bug fixes
- Tests for tool behavior and backend integration expectations

## What does not belong here

- Private infrastructure credentials
- Internal-only business logic
- Admin-only or superadmin-only MCP tools unless explicitly requested by PlugLayer maintainers
- Breaking config changes without migration notes

## Local development

From the repo root:

```bash
cd pluglayer-mcp
uv sync
```

Run the MCP locally:

```bash
uv run pluglayer-mcp
```

Run the HTTP entrypoint explicitly:

```bash
uv run pluglayer-mcp-http
```

## Validation

Before opening a PR, run:

```bash
python -m compileall pluglayer_mcp
python scripts/test_local_mcp_tools.py
```

If you are testing against a specific backend, set:

```bash
export PLUGLAYER_API_KEY=...
export PLUGLAYER_API_URL=http://localhost:8000
```

or:

```bash
export PLUGLAYER_API_URL=https://api.dev.pluglayer.com
```

## Pull request expectations

- Explain the problem clearly
- Describe the user-visible behavior change
- Include test or validation notes
- Mention any MCP tool name additions, removals, or schema changes
- Target the public `dev` branch unless a maintainer explicitly asks for a different base branch

## Security

- Never commit real tokens
- Do not hardcode internal endpoints
- Default examples should point to public-safe behavior
- Report security issues privately to maintainers instead of opening a public issue

## Maintainer workflow note

This public repository is synced from a private source repository. Maintainers may occasionally reshape commits or merge via sync branches. Please avoid force-pushing to branches you do not own.
