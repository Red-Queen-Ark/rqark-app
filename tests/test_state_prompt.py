import httpx
from rqark_core.types.prompt import PromptContext

from rqark_app.cloud.client import RQArkDataCloudClient
from rqark_app.prompts.memory import MemoryPrompt
from rqark_app.prompts.state import StatePrompt
from rqark_app.tools.context import AGENT_KEY, CLIENT_KEY
from rqark_app.types.cloud import CloudConfig

STATE = {'agent_id': 'agent-1', 'content': '## Now\n- Reworking the memory writer', 'version': 7, 'source': 'TUI', 'updated_at': '2026-10-20T01:00:00Z', 'created_at': '2026-10-01T00:00:00Z'}
MEMORIES = [{'id': 'm1', 'content': 'Boss works in UTC+8', 'occurred_at': '2026-09-01T00:00:00Z', 'pinned': False}]


def build_client(state: dict | None = STATE, memories: list[dict] | None = None, status: int = 200, seen: list[httpx.Request] | None = None) -> RQArkDataCloudClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, json={'state': state, 'memories': MEMORIES if memories is None else memories})

    client = RQArkDataCloudClient(CloudConfig(True, 'https://cloud.test', 'secret'))
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client


def context(client: object | None, agent_id: str | None = 'agent-1', extras: dict | None = None) -> PromptContext:
    extras = extras if extras is not None else {}
    if client is not None:
        extras[CLIENT_KEY] = client
    if agent_id is not None:
        extras[AGENT_KEY] = agent_id
    return PromptContext(extras=extras)


async def test_state_is_rendered_under_its_own_heading():
    client = build_client()
    text = await StatePrompt().get_messages(context(client))
    assert text is not None
    assert text.startswith('# Current State')
    assert '## Now\n- Reworking the memory writer' in text
    assert '以呢度為準' in text
    await client.aclose()


async def test_state_sits_before_memory_in_the_head():
    client = build_client()
    extras: dict = {}
    state_text = await StatePrompt().get_messages(context(client, extras=extras))
    memory_text = await MemoryPrompt().get_messages(context(client, extras=extras))
    assert state_text is not None and memory_text is not None
    assert StatePrompt.priority < MemoryPrompt.priority
    assert state_text.index('# Current State') == 0
    await client.aclose()


async def test_both_prompts_ask_the_cloud_once_per_turn():
    seen: list[httpx.Request] = []
    client = build_client(seen=seen)
    extras: dict = {}
    await StatePrompt().get_messages(context(client, extras=extras))
    await MemoryPrompt().get_messages(context(client, extras=extras))
    assert len(seen) == 1
    assert seen[0].url.path == '/api/memory/prompt'
    await client.aclose()


async def test_a_fresh_turn_asks_again():
    seen: list[httpx.Request] = []
    client = build_client(seen=seen)
    await StatePrompt().get_messages(context(client))
    await StatePrompt().get_messages(context(client))
    assert len(seen) == 2
    await client.aclose()


async def test_state_is_silent_without_a_pair():
    client = build_client()
    assert await StatePrompt().get_messages(context(None)) is None
    assert await StatePrompt().get_messages(context(client, agent_id=None)) is None
    await client.aclose()


async def test_state_is_silent_when_the_pair_has_none():
    client = build_client(state=None)
    assert await StatePrompt().get_messages(context(client)) is None
    await client.aclose()


async def test_state_is_silent_when_the_content_is_blank():
    client = build_client(state={**STATE, 'content': '   '})
    assert await StatePrompt().get_messages(context(client)) is None
    await client.aclose()


async def test_state_is_silent_when_the_cloud_fails():
    client = build_client(status=500)
    assert await StatePrompt().get_messages(context(client)) is None
    await client.aclose()


async def test_a_failed_read_does_not_hide_the_memory():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(500, json={'error': {'code': 'INTERNAL', 'message': 'boom'}})

    client = RQArkDataCloudClient(CloudConfig(True, 'https://cloud.test', 'secret'))
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    assert await StatePrompt().get_messages(context(client)) is None
    assert await MemoryPrompt().get_messages(context(client)) is None
    assert len(seen) == 2
    await client.aclose()
