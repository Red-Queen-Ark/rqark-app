import httpx2
import pytest
from rqark_core.types.provider import Provider

from rqark_app.cloud.chat import CloudAgentCore, RefreshingAuth
from rqark_app.cloud.client import RQArkDataCloudClient
from rqark_app.types.cloud import CloudConfig


def cloud_client(config: CloudConfig | None = None, on_unauthorized=None) -> RQArkDataCloudClient:
    return RQArkDataCloudClient(config or CloudConfig(True, 'https://cloud.test', 'token-1'), on_unauthorized=on_unauthorized)


def provider(provider_id: str | None) -> Provider:
    return Provider('deepseek-v4-pro', 'http://upstream', 0, None, id=provider_id)


def test_the_core_points_the_sdk_at_the_provider_by_id():
    client = CloudAgentCore(cloud_client())
    openai = client._get_client(provider('11111111-1111-1111-1111-111111111111'))
    assert str(openai.base_url).rstrip('/') == 'https://cloud.test/api/chat/11111111-1111-1111-1111-111111111111'
    assert openai.api_key == 'token-1'


def test_a_provider_without_an_id_is_refused():
    client = CloudAgentCore(cloud_client())
    with pytest.raises(ValueError):
        client._get_client(provider(None))


async def test_a_refused_request_is_repeated_after_the_token_refreshes():
    seen: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.headers['Authorization'])
        if len(seen) == 1:
            return httpx2.Response(401, json={'error': {'code': 'UNAUTHORIZED', 'message': 'expired'}})
        return httpx2.Response(200, json={'ok': True})

    async def refresh() -> None:
        client.config.api_key = 'token-2'

    client = cloud_client(on_unauthorized=refresh)
    auth = RefreshingAuth(client)
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler), auth=auth) as http:
        response = await http.post('https://cloud.test/api/chat/x/chat/completions', json={})

    assert response.status_code == 200
    assert seen == ['Bearer token-1', 'Bearer token-2']


async def test_a_second_refusal_is_passed_on():
    seen: list[str] = []
    refreshed = 0

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.headers['Authorization'])
        return httpx2.Response(401, json={'error': {'code': 'UNAUTHORIZED', 'message': 'expired'}})

    async def refresh() -> None:
        nonlocal refreshed
        refreshed += 1

    client = cloud_client(on_unauthorized=refresh)
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler), auth=RefreshingAuth(client)) as http:
        response = await http.post('https://cloud.test/api/chat/x/chat/completions', json={})

    assert response.status_code == 401
    assert len(seen) == 2
    assert refreshed == 1


async def test_without_a_refresh_hook_a_refusal_is_not_repeated():
    seen = 0

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal seen
        seen += 1
        return httpx2.Response(401, json={})

    client = cloud_client()
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler), auth=RefreshingAuth(client)) as http:
        response = await http.post('https://cloud.test/api/chat/x/chat/completions', json={})

    assert response.status_code == 401
    assert seen == 1
