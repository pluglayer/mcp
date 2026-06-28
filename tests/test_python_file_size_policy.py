from pathlib import Path


MAX_PYTHON_LINES = 500


def test_mcp_and_plugin_python_files_stay_within_size_limit():
    repo_root = Path(__file__).resolve().parents[2]
    oversized = []

    for surface in ("pluglayer-mcp", "plugins"):
        for path in (repo_root / surface).rglob("*.py"):
            if any(part in {".venv", "__pycache__"} for part in path.parts):
                continue
            line_count = len(path.read_text().splitlines())
            if line_count > MAX_PYTHON_LINES:
                oversized.append(f"{path.relative_to(repo_root)}: {line_count} lines")

    assert not oversized, (
        f"Python files in pluglayer-mcp/ and plugins/ must be at most "
        f"{MAX_PYTHON_LINES} lines:\n" + "\n".join(oversized)
    )
