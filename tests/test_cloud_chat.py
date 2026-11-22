import httpx2
import pytest
from rqark_core.types.provider import Provider

from rqark_app._app.helper import ChatHelper
from rqark_app.cloud.chat import CloudAgentCore, RefreshingAuth
from rqark_app.cloud.client import RQArkDataCloudClient
from rqark_app.provider.manager import ProviderManager
from rqark_app.session.manager import SessionManager
from rqark_app.session.storage import CloudStorage
from rqark_app.tools.context import AGENT_KEY, COMPACT_KEY, SESSION_KEY, SOURCE_KEY
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


def test_a_subagent_core_keeps_the_cloud_client():
    core = CloudAgentCore(cloud_client())
    child = core._spawn('child', ('root',), 600, {})
    assert isinstance(child, CloudAgentCore)
    assert child.cloud_client is core.cloud_client


def test_a_title_call_takes_its_source_from_cloud_storage():
    helper = ChatHelper(ProviderManager([provider(PROVIDER_ID)]), SessionManager(CloudStorage(cloud_client(), source='AGENT_CLOUD')), emit=lambda *args, **kwargs: None)
    assert helper._usage_tags(SESSION_UUID) == {'source': 'AGENT_CLOUD', 'session_id': SESSION_UUID}


AGENT_UUID = '8e2f5d3b-2b2b-4b2b-9b2b-2b2b2b2b2b2b'
SESSION_UUID = '0f1e2d3c-1a1a-4a1a-8a1a-1a1a1a1a1a1a'
PROVIDER_ID = '11111111-1111-1111-1111-111111111111'


async def test_a_turn_reports_its_source_and_ids_to_the_proxy():
    core = CloudAgentCore(cloud_client(), extras={SOURCE_KEY: 'TUI', AGENT_KEY: AGENT_UUID, SESSION_KEY: SESSION_UUID})
    params = await core._build_chat_params(provider(PROVIDER_ID), [], [])
    assert params['extra_body'] == {'source': 'TUI', 'agent_id': AGENT_UUID, 'session_id': SESSION_UUID}


async def test_a_core_without_tags_sends_no_extra_body():
    core = CloudAgentCore(cloud_client())
    params = await core._build_chat_params(provider(PROVIDER_ID), [], [])
    assert 'extra_body' not in params


async def test_tags_merge_into_an_extra_body_the_provider_needs():
    core = CloudAgentCore(cloud_client(), extras={SOURCE_KEY: 'AGENT_CLOUD', SESSION_KEY: SESSION_UUID})
    thinking = Provider('deepseek-v4-pro', 'http://upstream', 0, None, id=PROVIDER_ID, thinking='enabled')
    params = await core._build_chat_params(thinking, [], [])
    assert params['extra_body']['chat_template_kwargs'] == {'enable_thinking': True}
    assert params['extra_body']['source'] == 'AGENT_CLOUD'


async def test_a_compaction_call_is_tagged_as_one():
    core = CloudAgentCore(cloud_client(), extras={SOURCE_KEY: 'TUI', COMPACT_KEY: True})
    params = await core._build_chat_params(provider(PROVIDER_ID), [], [])
    assert params['extra_body']['is_compaction'] is True
