"""End-user feedback MCP tools."""

from __future__ import annotations

import re
from typing import Literal

from pluglayer_mcp.tools.shared import _client, _compact_error


FeedbackCategory = Literal["bug", "idea", "question", "compute_request", "other"]

_SECRET_PATTERNS = (
    re.compile(r"(?i)\b(authorization\s*:\s*bearer|bearer)\s+[^\s,;]+"),
    re.compile(
        r"(?i)\b([A-Z][A-Z0-9_]*(?:TOKEN|KEY|SECRET|PASSWORD)|"
        r"API[_-]?KEY|ACCESS[_-]?TOKEN|PASSWORD)\s*=\s*[^\s,;]+"
    ),
    re.compile(
        r'''(?i)(["']?(?:api[_-]?key|access[_-]?token|token|secret|password)["']?\s*:\s*)["'][^"']+["']'''
    ),
)


def _redact_sensitive(value: str) -> str:
    redacted = value
    redacted = _SECRET_PATTERNS[0].sub(lambda match: f"{match.group(1)} [REDACTED]", redacted)
    redacted = _SECRET_PATTERNS[1].sub(lambda match: f"{match.group(1)}=[REDACTED]", redacted)
    redacted = _SECRET_PATTERNS[2].sub(lambda match: f'{match.group(1)}"[REDACTED]"', redacted)
    return redacted.strip()


def _safe_optional(value: str, limit: int) -> str:
    return _redact_sensitive(value or "")[:limit].strip()


def _feedback_description(
    description: str,
    *,
    affected_tool: str,
    expected_behavior: str,
    actual_behavior: str,
    error_summary: str,
) -> str:
    sections = [_safe_optional(description, 4200)]
    context = (
        ("Source", "PlugLayer MCP/plugin"),
        ("Affected MCP tool", affected_tool),
        ("Expected behavior", expected_behavior),
        ("Actual behavior", actual_behavior),
        ("Error summary", error_summary),
    )
    for label, value in context:
        cleaned = _safe_optional(value, 800)
        if cleaned:
            sections.append(f"{label}: {cleaned}")
    return "\n\n".join(section for section in sections if section)[:6000]


def _feedback_line(item: dict) -> str:
    status = item.get("status", "unknown")
    category = item.get("category", "other")
    title = item.get("title", "Untitled feedback")
    return f"- **{title}** — {category} | {status} | id: `{item.get('id', 'unknown')}`"


def register_feedback_tools(mcp):
    @mcp.tool()
    async def submit_feedback(
        title: str,
        description: str,
        category: FeedbackCategory = "bug",
        page_url: str = "",
        page_path: str = "",
        page_title: str = "",
        affected_tool: str = "",
        expected_behavior: str = "",
        actual_behavior: str = "",
        error_summary: str = "",
    ) -> str:
        """Submit safe, actionable product feedback for the authenticated user.

        Use after explicit user requests, or automatically once after an actionable PlugLayer
        operation failure. Ask before submitting inferred, non-blocking improvement ideas.
        Never include credentials, environment values, private source, or full logs.
        """
        try:
            payload = await _client().post_form(
                "/v1/plugin/feedback",
                {
                    "title": _safe_optional(title, 140),
                    "description": _feedback_description(
                        description,
                        affected_tool=affected_tool,
                        expected_behavior=expected_behavior,
                        actual_behavior=actual_behavior,
                        error_summary=error_summary,
                    ),
                    "category": category,
                    "page_url": _safe_optional(page_url, 2000),
                    "page_path": _safe_optional(page_path, 500),
                    "page_title": _safe_optional(page_title, 300),
                },
            )
            feedback = payload.get("feedback", payload)
            return (
                "✅ Feedback submitted to PlugLayer.\n"
                f"Ticket: `{feedback.get('id', 'unknown')}`\n"
                f"Category: {feedback.get('category', category)}\n"
                f"Status: {feedback.get('status', 'open')}\n"
                f"Title: {feedback.get('title', title)}"
            )
        except Exception as exc:
            return _compact_error("Error submitting feedback", exc)

    @mcp.tool()
    async def list_my_feedback(limit: int = 20) -> str:
        """List feedback submitted by the authenticated PlugLayer user and show each status."""
        try:
            payload = await _client().get("/v1/plugin/feedback", params={"limit": min(max(limit, 1), 100)})
            items = payload.get("feedback", [])
            if not items:
                return "No feedback tickets found for the authenticated user."
            return "Your PlugLayer feedback:\n\n" + "\n".join(_feedback_line(item) for item in items)
        except Exception as exc:
            return _compact_error("Error listing feedback", exc)

    @mcp.tool()
    async def get_feedback(feedback_id: str) -> str:
        """Get one owned feedback ticket, including its status and resolution note."""
        try:
            payload = await _client().get(f"/v1/plugin/feedback/{feedback_id}")
            item = payload.get("feedback", payload)
            resolution = item.get("resolution_note") or "No resolution note yet."
            return (
                f"**{item.get('title', 'Untitled feedback')}**\n"
                f"Ticket: `{item.get('id', feedback_id)}`\n"
                f"Category: {item.get('category', 'other')}\n"
                f"Status: {item.get('status', 'unknown')}\n"
                f"Page: {item.get('page_url') or item.get('page_path') or 'not attached'}\n\n"
                f"{item.get('description', '')}\n\n"
                f"Resolution: {resolution}"
            )
        except Exception as exc:
            return _compact_error("Error loading feedback", exc)

    @mcp.tool()
    async def update_my_feedback(
        feedback_id: str,
        title: str = "",
        description: str = "",
    ) -> str:
        """Update the title or description of feedback owned by the authenticated user.

        Use this to clarify a report or consolidate repetitive feedback. List existing tickets
        first when a new report may duplicate one. Status and resolution remain admin-managed.
        Never include credentials, environment values, private source, or full logs.
        """
        cleaned_id = (feedback_id or "").strip()
        if not cleaned_id:
            return "Error updating feedback: feedback_id is required."

        updates = {}
        if title:
            updates["title"] = _safe_optional(title, 140)
        if description:
            updates["description"] = _safe_optional(description, 6000)
        if not updates:
            return "Error updating feedback: provide a new title or description."

        try:
            payload = await _client().patch(f"/v1/plugin/feedback/{cleaned_id}", data=updates)
            item = payload.get("feedback", payload)
            return (
                "✅ Feedback updated.\n"
                f"Ticket: `{item.get('id', cleaned_id)}`\n"
                f"Status: {item.get('status', 'unknown')}\n"
                f"Title: {item.get('title', updates.get('title', 'unchanged'))}"
            )
        except Exception as exc:
            return _compact_error("Error updating feedback", exc)
