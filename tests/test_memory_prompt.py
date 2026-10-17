import httpx
from rqark_core.types.prompt import PromptContext

from rqark_app.cloud.client import RQArkDataCloudClient
from rqark_app.prompts.memory import MemoryPrompt
from rqark_app.tools.context import AGENT_KEY, CLIENT_KEY
from rqark_app.types.cloud import CloudConfig

ROWS = [{'id': 'm1', 'content': 'Boss prefers short replies', 'occurred_at': '2026-10-01T00:00:00Z', 'pinned': True}, {'id': 'm2', 'content': 'Boss works in UTC+8', 'occurred_at': '2026-09-01T00:00:00Z', 'pinned': False}]


def build_client(rows: list[dict] | None = None, status: int = 200) -> RQArkDataCloudClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=ROWS if rows is None else rows)

    client = RQArkDataCloudClient(CloudConfig(True, 'https://cloud.test', 'secret'))
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client


def context(client: object | None, agent_id: str | None = 'agent-1') -> PromptContext:
    extras: dict = {}
    if client is not None:
        extras[CLIENT_KEY] = client
    if agent_id is not None:
        extras[AGENT_KEY] = agent_id
    return PromptContext(extras=extras)


async def test_prompt_lists_the_rows_with_their_time_and_pin():
    client = build_client()
    text = await MemoryPrompt().get_messages(context(client))
    assert text is not None
    assert '# Memory' in text
    assert '- [2026-10-01 00:00 UTC pinned] Boss prefers short replies' in text
    assert '- [2026-09-01 00:00 UTC] Boss works in UTC+8' in text
    assert text.index('prefers short replies') < text.index('works in UTC+8')
    await client.aclose()


async def test_prompt_renders_a_local_offset_as_utc():
    client = build_client(rows=[{'id': 'm1', 'content': 'a fact', 'occurred_at': '2026-10-01T08:00:00+08:00', 'pinned': False}])
    text = await MemoryPrompt().get_messages(context(client))
    assert text is not None
    assert '- [2026-10-01 00:00 UTC] a fact' in text
    await client.aclose()


async def test_prompt_is_silent_without_a_cloud_client():
    assert await MemoryPrompt().get_messages(context(None)) is None
    assert await MemoryPrompt().get_messages(PromptContext()) is None
    assert await MemoryPrompt().get_messages(None) is None


async def test_prompt_is_silent_without_an_agent_id():
    client = build_client()
    assert await MemoryPrompt().get_messages(context(client, agent_id=None)) is None
    await client.aclose()


async def test_prompt_is_silent_when_the_log_is_empty():
    client = build_client(rows=[])
    assert await MemoryPrompt().get_messages(context(client)) is None
    await client.aclose()


async def test_prompt_is_silent_when_the_cloud_fails():
    client = build_client(status=500)
    assert await MemoryPrompt().get_messages(context(client)) is None
    await client.aclose()


async def test_prompt_asks_for_the_pair_the_chat_runs_under():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=ROWS)

    client = RQArkDataCloudClient(CloudConfig(True, 'https://cloud.test', 'secret'))
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await MemoryPrompt().get_messages(context(client, agent_id='agent-9'))
    assert seen[0].url.path == '/api/memory/prompt'
    assert seen[0].content == b'{"agent_id":"agent-9"}'
    await client.aclose()
