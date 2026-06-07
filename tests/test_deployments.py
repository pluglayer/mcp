from pluglayer_mcp.tools.deployments import _compose_build_commands, _find_existing_project_app_match


def test_compose_build_commands_formats_local_build_steps():
    plan = {
        "services": [
            {
                "service_name": "worker",
                "strategy": "local_build_image",
                "build_context": ".",
                "build_dockerfile": "Dockerfile.worker",
                "command_args": ["python worker.py"],
            }
        ]
    }

    output = _compose_build_commands(plan, "/repo", "my-stack")

    assert "docker" in output
    assert "Dockerfile.worker" in output
    assert ".pluglayer/worker.oci.tar" in output
    assert 'local_image_archives={"worker": "/repo/.pluglayer/worker.oci.tar"}' in output


def test_find_existing_project_app_match_prefers_exact_slug():
    apps = [
        {"id": "1", "name": "agents-marketplace-api-r22", "route_slug": "agents-marketplace-api-r22"},
        {"id": "2", "name": "agents-marketplace-api", "route_slug": "agents-marketplace-api"},
    ]

    match = _find_existing_project_app_match(
        apps,
        name="agents-marketplace-api-r22",
        route_slug="agents-marketplace-api",
    )

    assert match
    assert match["id"] == "2"


def test_find_existing_project_app_match_falls_back_to_name():
    apps = [
        {"id": "9", "name": "billing-worker", "route_slug": "billing-worker-live"},
    ]

    match = _find_existing_project_app_match(
        apps,
        name="billing-worker",
        route_slug="",
    )

    assert match
    assert match["id"] == "9"
