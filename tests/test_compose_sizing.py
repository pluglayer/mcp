import asyncio

from pluglayer_mcp.tools.deployment import compose


class FakeMCP:
    def __init__(self):
        self.tools = {}

    def tool(self):
        def register(function):
            self.tools[function.__name__] = function
            return function
        return register


def deploy(monkeypatch, steps, archives=None):
    posts = []
    uploads = []

    class Client:
        async def post(self, path, data):
            if path.endswith('/compose-plan'):
                return {'services': steps}
            posts.append((path, data))
            return {'task_id': 'task-1', 'app': {'id': 'app-1'}}

        async def post_multipart(self, path, **kwargs):
            uploads.append((path, kwargs))
            return {'task_id': 'task-2', 'app': {'id': 'app-2'}}

    async def ready(**kwargs):
        return {'can_deploy': True}

    async def remember(*args, **kwargs):
        pass

    monkeypatch.setattr(compose, '_client', Client)
    monkeypatch.setattr(compose, '_get_compute_summary', ready)
    monkeypatch.setattr(compose, '_remember_context', remember)
    mcp = FakeMCP()
    compose.register_compose_tools(mcp)
    result = asyncio.run(mcp.tools['deploy_compose'](
        project_id='project-1', compose_yaml='services: {}',
        local_image_archives=archives,
    ))
    assert 'Smart compose deployment queued' in result, result
    return posts, uploads


def step(name, strategy, cpu, ram):
    return {
        'service_name': name, 'strategy': strategy,
        'suggested_app_name': name, 'suggested_route_slug': name,
        'single_service_compose_yaml': f'services:\n  {name}:\n    image: example/app\n',
        'required_compute': {'cpu_cores': cpu, 'ram_gb': ram},
    }


def test_compose_and_scheduled_services_forward_distinct_backend_budgets(monkeypatch):
    # A 0.1 CPU service must not become the API's default 0.5 CPU reservation.
    posts, uploads = deploy(monkeypatch, [
        step('web', 'compose_service', 0.1, 0.125),
        step('cron', 'scheduled_job', 2.5, 3),
    ])
    assert not uploads
    assert posts[0][1]['source']['cpu_limit'] == '0.1'
    assert posts[0][1]['source']['memory_limit'] == '128Mi'
    assert posts[1][1]['source']['cpu_limit'] == '2.5'
    assert posts[1][1]['source']['memory_limit'] == '3072Mi'
    assert 'web' in posts[0][1]['source']['compose_yaml']
    assert 'cron' in posts[1][1]['source']['compose_yaml']


def test_local_build_upload_uses_backend_budget(monkeypatch, tmp_path):
    archive = tmp_path / 'image.oci.tar'
    archive.write_bytes(b'fixture')
    posts, uploads = deploy(monkeypatch, [step('build', 'local_build_image', 0.1, 0.125)],
                            {'build': str(archive)})
    assert not posts
    form = uploads[0][1]['form_data']
    assert form['cpu_limit'] == '0.1'
    assert form['memory_limit'] == '128Mi'
    assert uploads[0][1]['file_path'] == str(archive)


def test_database_routing_preserves_template_budget(monkeypatch):
    async def preview(**kwargs):
        return {}

    monkeypatch.setattr(compose, '_preview_database_runtime', preview)
    database = step('db', 'database_template', 2.5, 3)
    database['marketplace_template_id'] = 'template-1'
    posts, _ = deploy(monkeypatch, [database])
    assert posts[0][0] == '/v1/plugin/databases'
    assert posts[0][1]['template_id'] == 'template-1'
    assert posts[0][1]['cpu_limit'] == '2.5'
    assert posts[0][1]['memory_limit'] == '3072Mi'


def test_missing_plan_dimensions_leave_api_defaults_intact(monkeypatch):
    legacy = step('legacy', 'compose_service', 0.1, 0.125)
    legacy.pop('required_compute')
    posts, _ = deploy(monkeypatch, [legacy])
    assert 'cpu_limit' not in posts[0][1]['source']
    assert 'memory_limit' not in posts[0][1]['source']
