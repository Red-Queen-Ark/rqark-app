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
