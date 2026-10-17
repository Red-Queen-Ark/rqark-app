import json
from datetime import UTC, datetime
from typing import Any

import pytest
from rqark_core.types.tool import ToolContext

from rqark_app.tools import MemorySave, MemorySearch
from rqark_app.tools.context import AGENT_KEY, CLIENT_KEY, SOURCE_KEY


class FakeClient:
    def __init__(self) -> None:
        self.created: list[dict] = []
        self.searched: list[tuple] = []
        self.rows: list[dict] = []

    async def create_memory(self, payload: dict) -> dict:
        self.created.append(payload)
        return {'id': 'memory-1', 'content': payload['content'], 'occurred_at': payload.get('occurred_at')}

    async def search_memory(self, agent_id: str, query: str | None = None, keywords: list[str] | None = None, at: str | None = None) -> list[dict]:
        self.searched.append((agent_id, query, keywords, at))
        return self.rows


def context(client: FakeClient, agent_id: str = 'agent-1', source: str = 'TUI') -> ToolContext:
    return ToolContext(extras={CLIENT_KEY: client, AGENT_KEY: agent_id, SOURCE_KEY: source})


async def test_save_sends_the_pair_and_the_source():
    client = FakeClient()
    result = await MemorySave().run(ctx=context(client), content='Boss prefers short replies', keywords=['reply', 'style'])
    created = client.created[0]
    assert {key: created[key] for key in ('agent_id', 'content', 'source', 'keywords')} == {'agent_id': 'agent-1', 'content': 'Boss prefers short replies', 'source': 'TUI', 'keywords': ['reply', 'style']}
    assert json.loads(result)['id'] == 'memory-1'
    assert json.loads(result)['content'] == 'Boss prefers short replies'


async def test_save_defaults_an_absent_occurred_at_to_now():
    client = FakeClient()
    before = datetime.now(UTC)
    await MemorySave().run(ctx=context(client), content='a fact')
    occurred_at = datetime.fromisoformat(client.created[0]['occurred_at'])
    assert before <= occurred_at <= datetime.now(UTC)


async def test_save_passes_an_explicit_occurred_at_as_iso8601():
    client = FakeClient()
    await MemorySave().run(ctx=context(client), content='a fact', occurred_at='2026-10-01T00:00:00Z')
    assert client.created[0]['occurred_at'] == '2026-10-01T00:00:00Z'


async def test_save_accepts_a_datetime_and_normalizes_it_to_utc():
    client = FakeClient()
    await MemorySave().run(ctx=context(client), content='a fact', occurred_at=datetime(2026, 10, 1, 8, 0, tzinfo=UTC))
    assert client.created[0]['occurred_at'] == '2026-10-01T08:00:00+00:00'


async def test_save_passes_source_message_through():
    client = FakeClient()
    await MemorySave().run(ctx=context(client), content='a fact', source_message={'role': 'user', 'text': 'hi'})
    assert client.created[0]['source_message'] == {'role': 'user', 'text': 'hi'}


async def test_save_never_pins_even_when_the_caller_asks():
    client = FakeClient()
    await MemorySave().run(ctx=context(client), content='a fact', pinned=True)
    assert 'pinned' not in client.created[0]


def test_save_schema_does_not_offer_pinned():
    properties = MemorySave().get_openai_schema()['function']['parameters']['properties']
    assert 'pinned' not in properties


async def test_save_rejects_an_empty_content():
    with pytest.raises(TypeError):
        await MemorySave().run(ctx=context(FakeClient()), content='   ')


async def test_save_requires_the_cloud_client_in_extras():
    with pytest.raises(RuntimeError) as info:
        await MemorySave().run(ctx=ToolContext(extras={AGENT_KEY: 'agent-1', SOURCE_KEY: 'TUI'}), content='a fact')
    assert CLIENT_KEY in str(info.value)


async def test_save_requires_an_agent_id_in_extras():
    with pytest.raises(RuntimeError) as info:
        await MemorySave().run(ctx=ToolContext(extras={CLIENT_KEY: FakeClient(), SOURCE_KEY: 'TUI'}), content='a fact')
    assert AGENT_KEY in str(info.value)


async def test_save_requires_a_source_in_extras():
    with pytest.raises(RuntimeError) as info:
        await MemorySave().run(ctx=ToolContext(extras={CLIENT_KEY: FakeClient(), AGENT_KEY: 'agent-1'}), content='a fact')
    assert SOURCE_KEY in str(info.value)


async def test_search_uses_the_pair_from_extras():
    client = FakeClient()
    client.rows = [{'id': 'm1', 'content': 'Boss prefers short replies', 'keywords': ['reply'], 'occurred_at': '2026-10-01T00:00:00Z', 'pinned': False, 'hits': 3}]
    result = await MemorySearch().run(ctx=context(client), query='reply', keywords=['reply', 'style'], at='2026-10-01T00:00:00Z')
    assert client.searched == [('agent-1', 'reply', ['reply', 'style'], '2026-10-01T00:00:00Z')]
    assert json.loads(result) == [{'id': 'm1', 'content': 'Boss prefers short replies', 'keywords': ['reply'], 'occurred_at': '2026-10-01T00:00:00Z', 'pinned': False}]


async def test_search_without_arguments_sends_only_the_agent():
    client = FakeClient()
    await MemorySearch().run(ctx=context(client))
    assert client.searched == [('agent-1', None, None, None)]


def test_schemas_declare_the_tool_names():
    assert MemorySave().name == 'memory_save'
    assert MemorySearch().name == 'memory_search'
    save_schema: dict[str, Any] = MemorySave().get_openai_schema()
    assert save_schema['function']['parameters']['required'] == ['content']
