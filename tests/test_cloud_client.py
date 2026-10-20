import json

import httpx
import pytest

from rqark_app.cloud.client import DataCloudError, RQArkDataCloudClient
from rqark_app.types.cloud import CloudConfig

COLLECTIONS = ['agents', 'providers', 'sessions']


@pytest.fixture
async def build_client():
    clients: list[RQArkDataCloudClient] = []

    def build(handler) -> RQArkDataCloudClient:
        client = RQArkDataCloudClient(CloudConfig(True, 'https://cloud.test', 'secret'))
        client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        clients.append(client)
        return client

    yield build
    for client in clients:
        await client._client.aclose()


@pytest.mark.parametrize('collection', COLLECTIONS)
async def test_list_returns_the_whole_array(build_client, collection):
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=[{'id': str(i)} for i in range(5)])

    client = build_client(handler)
    items = await getattr(client, f'list_{collection}')()

    assert [item['id'] for item in items] == ['0', '1', '2', '3', '4']
    assert len(calls) == 1
    assert calls[0].url.path == f'/api/{collection}'
    assert not calls[0].url.params


@pytest.mark.parametrize('collection', COLLECTIONS)
async def test_list_slices_locally(build_client, collection):
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=[{'id': str(i)} for i in range(5)])

    client = build_client(handler)
    items = await getattr(client, f'list_{collection}')(limit=2, offset=3)

    assert [item['id'] for item in items] == ['3', '4']
    assert len(calls) == 1
    assert not calls[0].url.params


@pytest.mark.parametrize('collection', COLLECTIONS)
async def test_list_returns_empty_list_for_empty_body(build_client, collection):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    client = build_client(handler)

    assert await getattr(client, f'list_{collection}')() == []


@pytest.mark.parametrize('collection', COLLECTIONS)
async def test_list_raises_data_cloud_error(build_client, collection):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={'error': {'code': 'UNAUTHORIZED', 'message': 'nope'}})

    client = build_client(handler)

    with pytest.raises(DataCloudError) as info:
        await getattr(client, f'list_{collection}')()
    assert info.value.status_code == 401
    assert info.value.code == 'UNAUTHORIZED'
    assert info.value.message == 'nope'


async def test_list_agents_authorizes_with_the_api_key(build_client):
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=[])

    client = build_client(handler)
    await client.list_agents()

    assert calls[0].headers['Authorization'] == 'Bearer secret'


async def test_list_memory_sends_the_agent_and_cursor(build_client):
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={'items': [{'id': 'm1'}], 'next_cursor': 'abc'})

    client = build_client(handler)
    page = await client.list_memory(agent_id='agent-1', cursor='xyz', limit=100)

    assert page == {'items': [{'id': 'm1'}], 'next_cursor': 'abc'}
    assert calls[0].url.path == '/api/memory'
    assert dict(calls[0].url.params) == {'agent_id': 'agent-1', 'cursor': 'xyz', 'limit': '100'}


async def test_list_memory_sends_no_params_without_arguments(build_client):
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={'items': [], 'next_cursor': ''})

    client = build_client(handler)
    await client.list_memory()

    assert not calls[0].url.params


async def test_set_memory_pinned_patches_the_flag(build_client):
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={'id': 'm1', 'pinned': True})

    client = build_client(handler)
    assert await client.set_memory_pinned('m1', True) == {'id': 'm1', 'pinned': True}
    assert (calls[0].method, calls[0].url.path) == ('PATCH', '/api/memory/m1')
    assert json.loads(calls[0].content) == {'pinned': True}


async def test_search_memory_posts_only_the_fields_it_was_given(build_client):
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=[{'id': 'm1'}])

    client = build_client(handler)
    rows = await client.search_memory('agent-1', query='reply', keywords=['reply'], at='2026-10-01T00:00:00Z')

    assert rows == [{'id': 'm1'}]
    assert calls[0].url.path == '/api/memory/search'
    assert json.loads(calls[0].content) == {'agent_id': 'agent-1', 'query': 'reply', 'keywords': ['reply'], 'at': '2026-10-01T00:00:00Z'}


async def test_search_memory_sends_only_the_agent_without_terms(build_client):
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=[])

    client = build_client(handler)
    await client.search_memory('agent-1')

    assert json.loads(calls[0].content) == {'agent_id': 'agent-1'}


async def test_create_memory_posts_the_payload(build_client):
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(201, json={'id': 'm1'})

    client = build_client(handler)
    payload = {'agent_id': 'agent-1', 'content': 'a fact', 'source': 'TUI'}
    assert await client.create_memory(payload) == {'id': 'm1'}
    assert (calls[0].method, calls[0].url.path) == ('POST', '/api/memory')
    assert json.loads(calls[0].content) == payload


async def test_request_wraps_transport_errors(build_client):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError('connection refused')

    client = build_client(handler)

    with pytest.raises(DataCloudError) as info:
        await client.me()
    assert info.value.status_code == 0
    assert info.value.code == 'REQUEST_FAILED'


async def test_request_wraps_protocol_errors(build_client):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.RemoteProtocolError('server disconnected without sending a response')

    client = build_client(handler)

    with pytest.raises(DataCloudError) as info:
        await client.me()
    assert info.value.status_code == 0
    assert info.value.code == 'REQUEST_FAILED'


async def test_a_transport_error_names_the_cloud_it_could_not_reach(build_client):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError('connection refused')

    client = build_client(handler)

    with pytest.raises(DataCloudError) as info:
        await client.list_agents()
    assert 'https://cloud.test/api/agents' in info.value.message
    assert 'connection refused' in info.value.message


@pytest.mark.parametrize('collection', COLLECTIONS)
async def test_list_raises_on_a_body_that_is_not_json(build_client, collection):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b'<html>gateway</html>', headers={'content-type': 'text/html'})

    client = build_client(handler)

    with pytest.raises(DataCloudError) as info:
        await getattr(client, f'list_{collection}')()
    assert info.value.status_code == 200
    assert info.value.code == 'INVALID_RESPONSE'


async def test_me_raises_on_a_body_that_is_not_json(build_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b'{', headers={'content-type': 'application/json'})

    client = build_client(handler)

    with pytest.raises(DataCloudError) as info:
        await client.me()
    assert info.value.code == 'INVALID_RESPONSE'


async def test_an_error_body_that_is_not_json_keeps_the_status_code(build_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, content=b'<html>bad gateway</html>', headers={'content-type': 'text/html'})

    client = build_client(handler)

    with pytest.raises(DataCloudError) as info:
        await client.me()
    assert info.value.status_code == 502
    assert info.value.code == 'UNKNOWN'
    assert info.value.message == 'data cloud answered 502'


async def test_context_manager_closes_the_client(build_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    client = build_client(handler)

    async with client as opened:
        assert opened is client
        assert await client.me() == {}

    assert client._client.is_closed


async def test_list_sessions_query_is_the_source_when_one_is_given(build_client):
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=[])

    client = build_client(handler)
    await client.list_sessions(source='TUI')

    assert calls[0].url.path == '/api/sessions'
    assert calls[0].url.params.get('source') == 'TUI'


async def test_create_session_merges_the_source_into_the_payload(build_client):
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(201, json={})

    client = build_client(handler)
    await client.create_session({'uuid': 's1'}, source='TUI')

    assert json.loads(calls[0].content) == {'uuid': 's1', 'source': 'TUI'}


async def test_update_session_merges_the_source_into_the_payload(build_client):
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={})

    client = build_client(handler)
    await client.update_session('s1', {'title': 'spec'}, source='AGENT_CLOUD')

    assert json.loads(calls[0].content) == {'title': 'spec', 'source': 'AGENT_CLOUD'}


async def test_list_user_config_reads_every_setting(build_client):
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=[{'id': 'c1', 'key': 'memory.event_log', 'value': False}])

    client = build_client(handler)
    entries = await client.list_user_config()

    assert entries == [{'id': 'c1', 'key': 'memory.event_log', 'value': False}]
    assert calls[0].url.path == '/api/user-config'
    assert not calls[0].url.params


async def test_list_agent_defaults_reads_the_whole_array(build_client):
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=[{'id': 'd1', 'source': 'TUI', 'agent_id': 'a1'}])

    client = build_client(handler)
    defaults = await client.list_agent_defaults()

    assert [entry['source'] for entry in defaults] == ['TUI']
    assert calls[0].url.path == '/api/agent-defaults'
    assert not calls[0].url.params


async def test_get_agent_default_reads_one_source(build_client):
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={'id': 'd1', 'source': 'TUI', 'agent_id': 'a1'})

    client = build_client(handler)

    assert await client.get_agent_default('TUI') == {'id': 'd1', 'source': 'TUI', 'agent_id': 'a1'}
    assert calls[0].url.path == '/api/agent-defaults/TUI'


async def test_get_agent_default_is_none_when_the_source_has_none(build_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={'error': {'code': 'NOT_FOUND', 'message': 'Agent default not found.'}})

    client = build_client(handler)

    assert await client.get_agent_default('TUI') is None


async def test_get_agent_default_raises_on_another_error(build_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={'error': {'code': 'UNAUTHORIZED', 'message': 'nope'}})

    client = build_client(handler)

    with pytest.raises(DataCloudError) as info:
        await client.get_agent_default('TUI')
    assert info.value.code == 'UNAUTHORIZED'


async def test_set_agent_default_puts_the_agent_id(build_client):
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={'id': 'd1', 'source': 'TUI', 'agent_id': 'a1'})

    client = build_client(handler)
    default = await client.set_agent_default('TUI', 'a1')

    assert default['agent_id'] == 'a1'
    assert calls[0].method == 'PUT'
    assert calls[0].url.path == '/api/agent-defaults/TUI'
    assert json.loads(calls[0].content) == {'agent_id': 'a1'}


async def test_delete_agent_default_reports_whether_it_was_there(build_client):
    responses = [httpx.Response(204), httpx.Response(404, json={'error': {'code': 'NOT_FOUND', 'message': 'Agent default not found.'}})]

    def handler(request: httpx.Request) -> httpx.Response:
        return responses.pop(0)

    client = build_client(handler)

    assert await client.delete_agent_default('TUI') is True
    assert await client.delete_agent_default('TUI') is False


async def test_delete_agent_default_raises_on_another_error(build_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={'error': {'code': 'INTERNAL', 'message': 'boom'}})

    client = build_client(handler)

    with pytest.raises(DataCloudError) as info:
        await client.delete_agent_default('TUI')
    assert info.value.status_code == 500


async def test_task_calls_hit_the_task_endpoints(build_client):
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.method == 'DELETE':
            return httpx.Response(204)
        if request.url.path == '/api/tasks':
            if request.method == 'GET':
                return httpx.Response(200, json=[{'id': 't1'}])
            return httpx.Response(201, json={'id': 't1'})
        return httpx.Response(200, json={'id': 't1'})

    client = build_client(handler)

    assert await client.list_tasks() == [{'id': 't1'}]
    assert await client.create_task({'name': 'Morning brief'}) == {'id': 't1'}
    assert (await client.update_task('t1', {'enabled': False}))['id'] == 't1'
    assert (await client.run_task('t1'))['id'] == 't1'
    await client.delete_task('t1')

    assert [(call.method, call.url.path) for call in calls] == [('GET', '/api/tasks'), ('POST', '/api/tasks'), ('PUT', '/api/tasks/t1'), ('POST', '/api/tasks/t1/run'), ('DELETE', '/api/tasks/t1')]
    assert json.loads(calls[1].content) == {'name': 'Morning brief'}
    assert json.loads(calls[2].content) == {'enabled': False}


async def test_list_task_runs_sends_the_page(build_client):
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={'items': [], 'next_cursor': None})

    client = build_client(handler)
    await client.list_task_runs('t1', limit=20, offset=40)

    assert calls[0].url.path == '/api/tasks/t1/runs'
    assert dict(calls[0].url.params) == {'limit': '20', 'offset': '40'}


async def test_list_sops_follows_the_cursor(build_client):
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.params.get('cursor'):
            return httpx.Response(200, json={'items': [{'slug': 'bravo'}], 'next_cursor': ''})
        return httpx.Response(200, json={'items': [{'slug': 'alpha'}], 'next_cursor': 'YnJhdm8'})

    client = build_client(handler)
    sops = await client.list_sops()

    assert [sop['slug'] for sop in sops] == ['alpha', 'bravo']
    assert calls[0].url.params.get('cursor') is None
    assert calls[1].url.params.get('cursor') == 'YnJhdm8'
    assert calls[0].url.path == '/api/sops'


async def test_sop_calls_hit_the_sop_endpoints(build_client):
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.method == 'DELETE':
            return httpx.Response(204)
        if request.method == 'GET':
            return httpx.Response(200, json={'items': [], 'next_cursor': ''})
        return httpx.Response(200, json={'slug': 'trip-itinerary', 'content': '# Trip'})

    client = build_client(handler)
    await client.get_sop('trip-itinerary')
    await client.create_sop({'slug': 'trip-itinerary', 'content': '# Trip'})
    await client.update_sop('trip-itinerary', {'content': '# Trip'})
    await client.delete_sop('trip-itinerary')

    assert [(call.method, call.url.path) for call in calls] == [('GET', '/api/sops/trip-itinerary'), ('POST', '/api/sops'), ('PATCH', '/api/sops/trip-itinerary'), ('DELETE', '/api/sops/trip-itinerary')]
    assert json.loads(calls[2].content) == {'content': '# Trip'}
