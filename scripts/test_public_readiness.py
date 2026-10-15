"""Real local stdio inventory and read/negative sweep; output contains no response values.

Requires a saved basithedev credential. Writes only a sanitized JSON coverage report.
Negative probes use nonexistent IDs and never count as success-path verification.
"""
import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'pluglayer-mcp'))
from pluglayer_mcp.credentials import resolve_api_base_url, resolve_api_key

FAKE = '00000000-0000-4000-8000-000000000000'
UUID_RE = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', re.I)
SAMPLE_COMPOSE = "services:\n  web:\n    image: nginxinc/nginx-unprivileged:alpine\n    ports: ['8080:8080']\n"
NF = r'not found|404'


def first_id(text):
    return next((v for v in UUID_RE.findall(text or '') if v != FAKE), None)


async def sweep(output):
    env = {'PYTHONPATH': str(ROOT / 'pluglayer-mcp'), 'PLUGLAYER_API_KEY': resolve_api_key(),
           'PLUGLAYER_API_URL': resolve_api_base_url(),
           'PLUGLAYER_CREDENTIALS_FILE': str(ROOT / '.readiness-no-credentials')}
    server = StdioServerParameters(command=sys.executable, args=['-m', 'pluglayer_mcp.server'], env=env)
    records = []
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            catalog = {t.name: t for t in (await session.list_tools()).tools}
            async def call(name, args, kind='read', expect=None):
                try:
                    result = await asyncio.wait_for(session.call_tool(name, args), 180)
                    text = '\n'.join(getattr(c, 'text', '') for c in result.content)
                    ok = (bool(re.search(expect, text, re.I)) and (bool(result.isError) or text.startswith('Confirmation required.'))) if expect else not result.isError
                    status = 'PASS' if ok else 'FAIL'
                    if name == 'close_template_launch_session' and re.search(r'404 Not Found: Not Found', text):
                        status = 'BLOCKED_BACKEND_ROUTE'
                    # No backend text, arguments, env/secret values or personal data in output.
                    code = next((c for c in (401,403,404,409,422,500,502,503,504) if re.search(r'\b'+str(c)+r'\b', text)), None)
                    records.append({'tool': name, 'kind': kind, 'status': status, 'is_error': bool(result.isError), 'http_status': code})
                    print(f'{status}: {name} ({kind}, isError={result.isError}, HTTP={code})', flush=True)
                    output.write_text(json.dumps({'account': 'basithedev', 'transport': 'local stdio', 'catalog': sorted(catalog), 'cases': records}, indent=2)+'\n')
                    return text
                except Exception as exc:
                    records.append({'tool': name, 'kind': kind, 'status': 'ERROR', 'exception': type(exc).__name__})
                    print(f'ERROR: {name} ({type(exc).__name__})', flush=True)
                    return ''
            identity = await call('get_current_user', {})
            if not re.search(r'Username: basithedev(?:@gmail\.com)?(?:\n|$)', identity):
                raise RuntimeError('Saved credential is not basithedev; refusing tests')
            P = first_id(await call('list_projects', {}))
            A = first_id(await call('list_deployments', {}))
            D = first_id(await call('list_user_databases', {}))
            T = first_id(await call('list_marketplace_templates', {}))
            F = first_id(await call('list_my_feedback', {}))
            READ = [
                ('get_current_user', {}),
                ('get_user_context', {}),
                ('list_projects', {}),
                ('get_my_projects', {}),
                ('list_deployments', {}),
                ('get_compute_summary', {}),
                ('get_my_available_compute', {}),
                ('get_my_available_computes', {}),
                ('list_nodes', {}),
                ('list_pluglayer_compute_options', {}),
                ('get_shared_compute_pricing', {}),
                ('estimate_compute', {'use_case': 'One API and a small postgres'}),
                ('list_registries', {}),
                ('list_user_databases', {}),
                ('list_database_templates', {}),
                ('list_marketplace_templates', {}),
                ('list_template_categories', {}),
                ('get_template_authoring_schema', {}),
                ('list_my_templates', {}),
                ('list_my_feedback', {}),
                ('list_my_notifications', {}),
                ('get_template_agent_context', {}),
                ('inspect_local_github_repo', {'repo_path': '.'}),
                ('preview_template_compose', {'compose_yaml': SAMPLE_COMPOSE}),
                ('detect_custom_domain_provider', {'domain': 'pluglayer.com'}),
            ]
            if P:
                READ += [('get_project', {'project_id': P}), ('get_apps_by_project', {'project_id': P}), ('list_deployments', {'project_id': P}), ('get_compute_summary', {'project_id': P}), ('list_nodes', {'project_id': P}), ('list_attachable_project_nodes', {'project_id': P}), ('list_project_domains', {'project_id': P}), ('get_domains_by_project', {'project_id': P}), ('list_user_databases', {'project_id': P}), ('check_slug_availability', {'project_id': P, 'slug': 'zz-nb-probe'}), ('check_database_slug_availability', {'project_id': P, 'slug': 'zz-nb-probe-db'}), ('plan_dedicated_compute', {'workload_name': 'nb-probe', 'cpu_cores': 0.25, 'ram_gb': 0.5, 'project_id': P}), ('analyze_compose_deploy_plan', {'project_id': P, 'compose_yaml': SAMPLE_COMPOSE}), ('get_compose_local_build_commands', {'project_id': P, 'compose_yaml': 'services:\n  api:\n    build: ./api\n'})]
            if P and A:
                READ += [('generate_github_actions', {'project_id': P, 'app_id': A})]
            if A:
                READ += [('get_deployment_status', {'deployment_id': A}), ('get_app_logs', {'app_id': A, 'lines': 10}), ('get_logs', {'deployment_id': A, 'lines': 10}), ('get_app_access_policy', {'app_id': A}), ('get_app_connection_env_vars', {'app_id': A}), ('exec_app_terminal', {'app_id': A, 'command': 'echo mcp-notebook-probe'})]
            if D:
                READ += [('get_database_logs', {'database_id': D, 'lines': 5}), ('get_database_connection_details', {'database_id': D})]
            if T:
                READ += [('get_marketplace_template', {'template_id_or_slug': T}), ('get_template_details', {'template_id': T}), ('list_template_launch_sessions', {'template_id': T})]
            if F:
                READ += [('get_feedback', {'feedback_id': F})]
            PROBES = [
                ('restart_app', {'app_id': FAKE}, NF),
                ('restart_database', {'database_id': FAKE}, NF),
                ('redeploy', {'deployment_id': FAKE, 'confirmed_app_name': 'nope'}, NF),
                ('rollback', {'deployment_id': FAKE}, NF),
                ('remove_app', {'app_id': FAKE}, NF),
                ('delete_app', {'app_id': FAKE}, NF),
                ('delete_deployment', {'deployment_id': FAKE}, NF),
                ('remove_database', {'database_id': FAKE}, NF),
                ('delete_database', {'database_id': FAKE}, NF),
                ('remove_project', {'project_id': FAKE}, NF),
                ('delete_project', {'project_id': FAKE}, NF),
                ('rename_project', {'project_id': FAKE, 'new_name': 'probe'}, NF),
                ('update_project_metadata', {'project_id': FAKE, 'description': 'x'}, NF),
                ('apply_app_env_vars', {'app_id': FAKE, 'env_vars': {'A': '1'}, 'restart_mode': 'none'}, NF),
                ('sync_database_env_to_app', {'database_id': FAKE, 'app_id': FAKE}, NF),
                ('update_app_domain', {'app_id': FAKE, 'route_slug': 'zz-probe'}, NF),
                ('add_custom_domain', {'project_id': FAKE, 'domain': 'probe.invalid'}, NF),
                ('attach_custom_domain', {'domain_id': FAKE, 'app_id': FAKE}, NF),
                ('verify_custom_domain', {'domain_id': FAKE}, NF),
                ('detach_custom_domain', {'domain_id': FAKE}, NF),
                ('update_app_access_policy', {'app_id': FAKE, 'confirmed_app_name': 'nope', 'http_average': 100, 'http_burst': 200, 'http_period_seconds': 1, 'tcp_max_connections': 100, 'allowed_cidrs': []}, NF),
                ('mark_notification_read', {'notification_id': FAKE}, NF),
                ('update_my_feedback', {'feedback_id': FAKE, 'title': 'probe'}, NF),
                ('clone_template_draft', {'template_id': FAKE, 'name': 'zz-probe'}, NF),
                ('update_template_draft', {'template_id': FAKE, 'updates': {'description': 'x'}}, NF),
                ('delete_template_draft', {'template_id': FAKE, 'confirmation': f'DELETE TEMPLATE {FAKE}'}, NF),
                ('submit_template_for_approval', {'template_id': FAKE}, NF),
                ('create_template_launch_session', {'template_id': FAKE}, NF),
                ('update_app_from_template', {'app_id': FAKE}, NF),
                ('update_database_access', {'database_id': FAKE, 'tcp_allowed_cidrs': []}, NF),
                ('deploy_image', {'project_id': FAKE, 'name': 'zz-probe', 'image': 'nginx'}, NF),
                ('deploy_compose', {'project_id': FAKE, 'compose_yaml': SAMPLE_COMPOSE}, NF),
                ('deploy_marketplace_template', {'template_id': T or FAKE, 'app_name': 'zz-probe', 'project_id': FAKE}, NF),
                ('create_database', {'template_id': FAKE, 'app_name': 'zz-probe', 'project_id': FAKE}, NF),
                ('attach_node_to_project', {'project_id': FAKE, 'node_id': FAKE}, NF),
                ('detach_node_from_project', {'project_id': FAKE, 'node_id': FAKE, 'confirm': False}, 'confirmation required'),
                ('request_extra_compute', {'workload_name': 'zz-probe', 'cpu_cores': 1, 'ram_gb': 1, 'confirm': False}, 'confirmation required'),
                ('upload_image_archive_and_deploy', {'project_id': FAKE, 'name': 'zz', 'image_archive_path': '/nonexistent/x.tar'}, 'archive not found'),
                ('upload_image_archive_and_redeploy_app', {'app_id': FAKE, 'image_archive_path': '/nonexistent/x.tar'}, 'archive not found'),
                ('create_template_draft', {'template': {}}, '422|field required|missing'),
            ]
            for name, args in READ:
                if name in catalog:
                    await call(name, args)
            for section in ('create_draft', 'deploy', 'session'):
                await call('get_template_authoring_schema', {'section': section})
            await call('get_template_agent_context', {'section': 'templates', 'limit': 2})
            PROBES += [
                ('plan_template_launch', {'template_id': FAKE}, NF),
                ('run_template_agent', {'agent_type': 'use_template_agent', 'message': 'Readiness missing-resource test', 'template_id': FAKE}, NF),
                ('rename_project', {'project_id': FAKE, 'new_name': 'x'}, 'between 2 and 50'),
                ('apply_app_env_vars', {'app_id': FAKE, 'merge': False}, 'explicit source'),
            ]
            for name, args, expect in PROBES:
                if name == 'update_my_feedback':
                    continue  # Public guidance forbids edits to submitted feedback.
                if name in catalog:
                    await call(name, args, 'negative-only', expect)
            await call('close_template_launch_session', {'session_id': FAKE}, 'negative-only', NF)
            seen = {r['tool'] for r in records}
            for name in sorted(set(catalog) - seen):
                records.append({'tool': name, 'kind': 'not-run', 'status': 'NOT_RUN'})
            output.write_text(json.dumps({'account': 'basithedev', 'transport': 'local stdio', 'catalog': sorted(catalog), 'cases': records}, indent=2)+'\n')
    return records

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(sweep(args.output))

    results = json.loads(args.output.read_text())["cases"]
    raise SystemExit(1 if any(r["status"] not in {"PASS", "NOT_RUN"} for r in results) else 0)
