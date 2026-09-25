import httpx
import pytest

from rqark_app.cloud.client import DataCloudError, RQArkDataCloudClient
from rqark_app.types.cloud import CloudConfig

COLLECTIONS = ['agents', 'providers']


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


async def test_context_manager_closes_the_client(build_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    client = build_client(handler)

    async with client as opened:
        assert opened is client
        assert await client.me() == {}

    assert client._client.is_closed
