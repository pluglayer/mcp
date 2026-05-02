# Contributing to PlugLayer MCP

This repository exposes PlugLayer's end-user MCP server. Contributions should improve the end-user deployment experience, reliability, documentation, and safe integrations.

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

## Security

- Never commit real tokens
- Do not hardcode internal endpoints
- Default examples should point to public-safe behavior
- Report security issues privately to maintainers instead of opening a public issue

## Maintainer workflow note

This public repository is synced from a private source repository. Maintainers may occasionally reshape commits or merge via sync branches. Please avoid force-pushing to branches you do not own.
