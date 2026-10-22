import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from openai import APIError
from rqark_core.prompts import RolePrompt
from rqark_core.types.chat import AssistantMessage, Chunk, SystemMessage, ToolCall, ToolMessage, Usage, UserMessage
from rqark_core.types.event import AgentPayload
from rqark_core.types.provider import Provider
from rqark_core.types.tool import PlanItem

from rqark_app.app import AgentApp
from rqark_app.memory import USER_NAME_KEY
from rqark_app.session.manager import SessionManager
from rqark_app.session.storage import JSONLStorage
from rqark_app.types.agent import BaseAgent
from rqark_app.types.session import Session, parse_dt


class TestAgent(BaseAgent):
    name = 'wednesday'
    description = ''
    prompts = []
    tools = []


class RoleAgent(BaseAgent):
    name = 'angel'
    description = ''
    prompts = [RolePrompt('Angel Holiday', 'Boss')]
    tools = []


class FakeCore:
    instances: list['FakeCore'] = []
    errors = 0
    terminal_error: Exception | None = None
    reply_usage: Usage | None = None
    reply: list | None = None

    def __init__(self, agent_id: str = '', path: tuple[str, ...] = (), extras: dict | None = None):
        self.agent_id = agent_id
        self.path = path
        self.extras = extras
        self.chat_calls: list[tuple] = []
        FakeCore.instances.append(self)

    def on_chunk(self):
        return lambda f: f

    def on_message(self):
        return lambda f: f

    def on_plan(self):
        return lambda f: f

    async def chat(self, provider, messages, prompts, tools):
        self.chat_calls.append((provider, messages, prompts, tools))
        if FakeCore.terminal_error is not None:
            err, FakeCore.terminal_error = FakeCore.terminal_error, None
            return [*messages, AssistantMessage('partial')], err
        if FakeCore.errors > 0:
            FakeCore.errors -= 1
            request = httpx.Request('POST', 'http://test')
            return messages, APIError('boom', request=request, body=None)
        return [*messages, *(FakeCore.reply or [AssistantMessage('ok', usage=FakeCore.reply_usage)])], None


@pytest.fixture
def fake_core(monkeypatch):
    FakeCore.instances = []
    FakeCore.errors = 0
    FakeCore.terminal_error = None
    FakeCore.reply_usage = None
    FakeCore.reply = None
    monkeypatch.setattr('rqark_app._app.core.AgentCore', FakeCore)
    return FakeCore


def make_app(*providers) -> AgentApp:
    return AgentApp(list(providers))


async def test_chat_passes_path_and_composite_agent_id(fake_core):
    app = make_app(Provider('m', 'http://x', 0, 'k', name='p1'))
    await app.chat('hi', TestAgent(), path=('parent:1',))
    core = fake_core.instances[0]
    assert core.path == ('parent:1',)
    assert core.agent_id.startswith('wednesday:')


async def test_chat_default_path_is_empty(fake_core):
    app = make_app(Provider('m', 'http://x', 0, 'k', name='p1'))
    await app.chat('hi', TestAgent())
    assert fake_core.instances[0].path == ()


async def test_chat_passes_extras_to_the_core(fake_core):
    app = make_app(Provider('m', 'http://x', 0, 'k', name='p1'))
    extras = {'data_cloud': 'client', 'agent_id': 'agent-1', 'source': 'TUI'}
    await app.chat('hi', TestAgent(), extras=extras)
    assert fake_core.instances[0].extras is extras


async def test_chat_without_extras_leaves_the_core_extras_empty(fake_core):
    app = make_app(Provider('m', 'http://x', 0, 'k', name='p1'))
    await app.chat('hi', TestAgent())
    assert fake_core.instances[0].extras is None


async def test_chat_carries_the_role_prompt_user_name_in_extras(fake_core):
    app = make_app(Provider('m', 'http://x', 0, 'k', name='p1'))
    extras: dict = {'agent_id': 'agent-1'}
    await app.chat('hi', RoleAgent(), extras=extras)
    assert extras[USER_NAME_KEY] == 'Boss'


async def test_chat_without_a_role_prompt_uses_the_plain_user_name(fake_core):
    app = make_app(Provider('m', 'http://x', 0, 'k', name='p1'))
    extras: dict = {'agent_id': 'agent-1'}
    await app.chat('hi', TestAgent(), extras=extras)
    assert extras[USER_NAME_KEY] == 'User'


async def test_chat_emits_message_event_with_path(fake_core):
    app = make_app(Provider('m', 'http://x', 0, 'k', name='p1'))
    events = []

    async def on_msg(ev):
        events.append(ev)

    app.on_message()(on_msg)
    await app.chat('hi', TestAgent(), path=('parent:1',))
    assert len(events) == 1
    assert events[0].path == ('parent:1',)
    assert events[0].agent_id.startswith('wednesday:')
    assert events[0].payload.content == 'hi'


async def test_chat_creates_new_session(fake_core):
    app = make_app(Provider('m', 'http://x', 0, 'k', name='p1'))
    await app.chat('hi', TestAgent())
    assert len(app.session_mgr.sessions_map) == 1
    session = next(iter(app.session_mgr.sessions_map.values()))
    assert fake_core.instances[0].agent_id == f'wednesday:{session.uuid}'


async def test_chat_reuses_session_and_accumulates_history(fake_core):
    app = make_app(Provider('m', 'http://x', 0, 'k', name='p1'))
    await app.chat('first', TestAgent(), session_id='abc')
    await app.chat('second', TestAgent(), session_id='abc')
    assert set(app.session_mgr.sessions_map) == {'abc'}
    second_core = fake_core.instances[1]
    messages = second_core.chat_calls[0][1]
    assert [m.content for m in messages] == ['first', 'ok', 'second']


async def test_provider_switched_emits_event(fake_core, monkeypatch):
    p1 = Provider('m1', 'http://a', 1, 'k', name='p1')
    p2 = Provider('m2', 'http://b', 2, 'k', name='p2')
    app = make_app(p1, p2)
    switches = []

    async def on_switch(ev):
        switches.append(ev)

    app.on_provider_switched()(on_switch)
    fake_core.errors = 3

    async def no_sleep(_):
        pass

    monkeypatch.setattr(asyncio, 'sleep', no_sleep)
    await app.chat('hi', TestAgent())
    assert len(switches) == 1
    assert switches[0].payload.old.name == 'p1'
    assert switches[0].payload.new.name == 'p2'
    assert app.provider_mgr.provider.name == 'p2'


async def test_usage_chunk_is_forwarded_as_a_usage_event(fake_core):
    app = make_app(Provider('m', 'http://x', 0, 'k', name='p1'))
    events = []

    async def on_usage(ev):
        events.append(ev)

    app.on_usage()(on_usage)
    await app.handle_chunk_event(AgentPayload('wednesday:abc', ('parent:1',), Chunk('usage', Usage(10, 5, 15))))

    assert len(events) == 1
    assert events[0].agent_id == 'wednesday:abc'
    assert events[0].path == ('parent:1',)
    assert events[0].payload.prompt_tokens == 10
    assert events[0].payload.completion_tokens == 5
    assert events[0].payload.total_tokens == 15


async def test_usage_chunk_without_a_usage_payload_is_ignored(fake_core):
    app = make_app(Provider('m', 'http://x', 0, 'k', name='p1'))
    events = []

    async def on_usage(ev):
        events.append(ev)

    app.on_usage()(on_usage)
    await app.handle_chunk_event(AgentPayload('wednesday:abc', (), Chunk('usage', 'not-a-usage')))

    assert events == []


async def test_chat_persists_the_assistant_usage_into_the_session(fake_core):
    app = make_app(Provider('m', 'http://x', 0, 'k', name='p1'))
    fake_core.reply_usage = Usage(100, 20, 120, cached_tokens=64, reasoning_tokens=8)

    session = await app.chat('hi', TestAgent(), session_id='abc')

    usage = session.history[-1].usage
    assert usage == Usage(100, 20, 120, cached_tokens=64, reasoning_tokens=8)
    assert usage.prompt_tokens > 0
    assert usage.cache_hit_rate == 0.64


async def test_chat_writes_usage_into_the_jsonl_file(fake_core, tmp_path):
    storage = JSONLStorage(tmp_path)
    app = AgentApp([Provider('m', 'http://x', 0, 'k', name='p1')], storage=storage)
    fake_core.reply_usage = Usage(100, 20, 120, cached_tokens=64, reasoning_tokens=8)

    await app.chat('hi', TestAgent(), session_id='abc')

    raw = next(iter(tmp_path.glob('*.jsonl'))).read_text(encoding='utf-8')
    assert '"usage"' in raw
    assert '"cached_tokens": 64' in raw


async def test_every_assistant_message_in_a_tool_turn_keeps_its_own_usage(fake_core):
    app = make_app(Provider('m', 'http://x', 0, 'k', name='p1'))
    fake_core.reply = [AssistantMessage('calling', tool_calls=[ToolCall('c1', 'function', 'fn', '{}')], usage=Usage(10, 1, 11)), ToolMessage('c1', 'result'), AssistantMessage('done', usage=Usage(20, 2, 22))]

    session = await app.chat('hi', TestAgent(), session_id='abc')

    usages = [m.usage for m in session.history if isinstance(m, AssistantMessage)]
    assert usages == [Usage(10, 1, 11), Usage(20, 2, 22)]


async def test_jsonl_storage_roundtrip(tmp_path):
    storage = JSONLStorage(tmp_path)
    session = Session(uuid='s1', title='t1')
    user_msg = UserMessage('hi')
    assistant_msg = AssistantMessage('yo', tool_calls=[ToolCall('c1', 'function', 'fn', '{}')], reasoning_content='think step', usage=Usage(1, 2, 3, cached_tokens=1, reasoning_tokens=1))
    session.history = [user_msg, assistant_msg]
    session.plan_items = [PlanItem('p1', 'do stuff', 'pending')]
    await storage.create(session)
    loaded = await storage.load()
    assert len(loaded) == 1
    s = loaded[0]
    assert s.uuid == 's1'
    assert s.title == 't1'
    assert s.created_at == session.created_at
    assert s.created_at.utcoffset() == timedelta(0)
    assert s.history[0].content == 'hi'
    assert isinstance(s.history[0], UserMessage)
    assert s.history[0].created_at == user_msg.created_at
    assert isinstance(s.history[1], AssistantMessage)
    assert s.history[1].tool_calls is not None
    assert s.history[1].tool_calls[0].id == 'c1'
    assert s.history[1].tool_calls[0].name == 'fn'
    assert s.history[1].reasoning_content == 'think step'
    assert s.history[1].created_at == assistant_msg.created_at
    assert s.history[1].created_at.utcoffset() == timedelta(0)
    assert s.history[1].usage == Usage(1, 2, 3, cached_tokens=1, reasoning_tokens=1)
    assert s.plan_items[0].content == 'do stuff'
    assert await storage.delete('s1') is True
    assert await storage.delete('s1') is False
    assert await storage.load() == []


async def test_jsonl_storage_loads_legacy_files_without_message_timestamps(tmp_path):
    file = tmp_path / 'legacy.jsonl'
    file.write_text(
        '\n'.join(
            [
                '{"uuid": "legacy", "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00", "title": "", "plan_items": []}',
                '{"role": "user", "content": "hi"}',
                '{"role": "assistant", "content": "yo", "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "fn", "arguments": "{}"}}]}',
            ]
        )
        + '\n',
        encoding='utf-8',
    )
    loaded = await JSONLStorage(tmp_path).load()
    s = loaded[0]
    assert [type(m).__name__ for m in s.history] == ['UserMessage', 'AssistantMessage']
    for m in s.history:
        assert isinstance(m, (UserMessage, AssistantMessage, ToolMessage, SystemMessage))
        assert m.created_at.tzinfo is not None


async def test_chat_persists_session_to_storage(fake_core, tmp_path):
    storage = JSONLStorage(tmp_path)
    app = AgentApp([Provider('m', 'http://x', 0, 'k', name='p1')], storage=storage)
    await app.chat('first', TestAgent(), session_id='abc')
    await app.chat('second', TestAgent(), session_id='abc')
    mgr = SessionManager(storage)
    await mgr.load()
    session = mgr.sessions_map['abc']
    assert [m.content for m in session.history] == ['first', 'ok', 'second', 'ok']


async def test_set_plan_updates_session_and_persists(tmp_path):
    storage = JSONLStorage(tmp_path)
    mgr = SessionManager(storage)
    await mgr.create('abc')
    items = [PlanItem('p1', 'do stuff', 'pending')]
    session = await mgr.set_plan('wednesday:abc', items)
    assert session is not None
    assert session.plan_items[0].content == 'do stuff'
    assert mgr.sessions_map['abc'].plan_items[0].content == 'do stuff'
    await mgr.save('abc')
    reloaded = SessionManager(storage)
    await reloaded.load()
    assert reloaded.sessions_map['abc'].plan_items[0].content == 'do stuff'


async def test_handle_save_plan_wires_to_session(fake_core):
    app = make_app(Provider('m', 'http://x', 0, 'k', name='p1'))
    await app.chat('hi', TestAgent(), session_id='abc')
    session = app.session_mgr.sessions_map['abc']
    ev = AgentPayload('wednesday:abc', ('parent:1',), [PlanItem('p1', 'do stuff', 'pending')])
    await app.handle_save_plan(ev)
    assert session.plan_items[0].content == 'do stuff'


async def test_chat_seeds_the_core_with_the_session_plan(fake_core):
    app = make_app(Provider('m', 'http://x', 0, 'k', name='p1'))
    await app.chat('hi', TestAgent(), session_id='abc')
    await app.handle_save_plan(AgentPayload('wednesday:abc', ('parent:1',), [PlanItem('p1', 'do stuff', 'in_progress')]))

    await app.chat('second', TestAgent(), session_id='abc')

    core = fake_core.instances[-1]
    assert [(p.id, p.content, p.status) for p in core.plan_items] == [('p1', 'do stuff', 'in_progress')]


async def test_chat_seeds_an_empty_plan_for_a_new_session(fake_core):
    app = make_app(Provider('m', 'http://x', 0, 'k', name='p1'))
    await app.chat('hi', TestAgent())
    assert fake_core.instances[-1].plan_items == []


async def test_chat_seeded_plan_items_are_copies(fake_core):
    app = make_app(Provider('m', 'http://x', 0, 'k', name='p1'))
    await app.chat('hi', TestAgent(), session_id='abc')
    session = app.session_mgr.sessions_map['abc']
    session.plan_items = [PlanItem('p1', 'do stuff', 'pending')]

    await app.chat('second', TestAgent(), session_id='abc')
    fake_core.instances[-1].plan_items[0].status = 'completed'

    assert session.plan_items[0].status == 'pending'


async def test_chat_seeds_the_plan_after_a_storage_reload(fake_core, tmp_path):
    storage = JSONLStorage(tmp_path)
    app = AgentApp([Provider('m', 'http://x', 0, 'k', name='p1')], storage=storage)
    await app.chat('hi', TestAgent(), session_id='abc')
    await app.handle_save_plan(AgentPayload('wednesday:abc', ('parent:1',), [PlanItem('p1', 'do stuff', 'pending')]))

    restarted = AgentApp([Provider('m', 'http://x', 0, 'k', name='p1')], storage=storage)
    await restarted.session_mgr.load()
    await restarted.chat('second', TestAgent(), session_id='abc')

    assert [p.content for p in fake_core.instances[-1].plan_items] == ['do stuff']


async def test_set_plan_ignores_unknown_agent(tmp_path):
    storage = JSONLStorage(tmp_path)
    mgr = SessionManager(storage)
    await mgr.create('abc')
    result = await mgr.set_plan('random-uuid', [PlanItem('p1', 'do stuff', 'pending')])
    assert result is None
    assert mgr.sessions_map['abc'].plan_items == []


def test_parse_dt_aware_normalizes_to_utc():
    dt = parse_dt('2026-01-01T08:00:00+08:00')
    assert dt == datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)


def test_parse_dt_naive_assumes_utc():
    dt = parse_dt('2026-01-01T08:00:00')
    assert dt == datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)


async def test_chat_saves_snapshot_on_terminal_error(fake_core, tmp_path):
    storage = JSONLStorage(tmp_path)
    app = AgentApp([Provider('m', 'http://x', 0, 'k', name='p1')], storage=storage)
    fake_core.terminal_error = RuntimeError('boom')
    with pytest.raises(RuntimeError):
        await app.chat('hi', TestAgent(), session_id='abc')
    assert [m.content for m in app.session_mgr.sessions_map['abc'].history] == ['hi', 'partial']
    reloaded = SessionManager(storage)
    await reloaded.load()
    assert [m.content for m in reloaded.sessions_map['abc'].history] == ['hi', 'partial']
