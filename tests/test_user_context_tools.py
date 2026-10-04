from pluglayer_mcp.tools.user_context import _context_update_summary


def test_context_update_summary_does_not_echo_large_payload():
    payload = {"history": "x" * 60_000, "projects": {"demo": {"app": "api"}}}

    result = _context_update_summary(payload)

    assert len(result) < 300
    assert "60,000" not in result
    assert "`history`" in result
    assert "get_user_context()" in result
