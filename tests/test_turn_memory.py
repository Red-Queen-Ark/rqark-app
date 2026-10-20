import asyncio
import json

import pytest
from rqark_core.types.chat import AssistantMessage, UserMessage
from rqark_core.types.provider import Provider

from rqark_app.app import AgentApp
from rqark_app.cloud.client import DataCloudError
from rqark_app.memory import writer as writer_module
from rqark_app.prompts.memory import PROMPT_KEY
from rqark_app.tools.context import AGENT_KEY, CLIENT_KEY, SOURCE_KEY
from rqark_app.types.session import Session


class FakeClient:
    def __init__(self) -> None:
        self.created: list[dict] = []
        self.states: list[dict] = []
        self.state_reads = 0
        self.fail = False

    async def create_memory(self, payload: dict) -> dict:
        if self.fail:
            raise DataCloudError(500, 'INTERNAL', 'boom')
        self.created.append(payload)
        return {'id': 'memory-1'}

    async def set_state(self, agent_id: str, content: str, source: str, version: int | None = None) -> dict:
        if self.fail:
            raise DataCloudError(500, 'INTERNAL', 'boom')
        self.states.append({'agent_id': agent_id, 'content': content, 'version': version})
        return {'version': 1}

    async def get_state(self, agent_id: str) -> dict | None:
        self.state_reads += 1
        return {'content': 'old board', 'version': 3}


@pytest.fixture
def model(monkeypatch):
    """The writer's model call, stubbed: these tests are about the wiring."""

    class FakeCore:
        answer = json.dumps({'skip': False, 'state': 'new board', 'events': [{'content': 'Boss 叫 agent 做嘢；agent 做完'}], 'facts': []})

        def __init__(self, agent_id: str = '', path=(), extras=None):
            pass

        async def chat(self, provider, messages, prompts, tools):
            return [*messages, AssistantMessage(FakeCore.answer)], None

    monkeypatch.setattr(writer_module, 'AgentCore', FakeCore)
    return FakeCore


def make_app() -> AgentApp:
    return AgentApp([Provider('m', 'http://x', 0, 'k', name='p1')])


def extras(client: FakeClient | None, agent_id: str | None = 'agent-1') -> dict:
    built: dict = {SOURCE_KEY: 'TUI'}
    if client is not None:
        built[CLIENT_KEY] = client
    if agent_id is not None:
        built[AGENT_KEY] = agent_id
    return built


def finished_session() -> Session:
    session = Session()
    session.history = [UserMessage('Boss 叫 agent 修好 memory writer'), AssistantMessage('x' * 400)]
    return session


async def test_a_finished_turn_writes_an_event_and_the_state(model):
    client = FakeClient()
    app = make_app()

    await app.write_turn_memory(session_id='s1', source='TUI', session=finished_session(), extras=extras(client))

    assert [row['kind'] for row in client.created] == ['event']
    assert client.created[0]['agent_id'] == 'agent-1'
    assert client.created[0]['source'] == 'TUI'
    assert client.states == [{'agent_id': 'agent-1', 'content': 'new board', 'version': 3}]


async def test_the_state_the_prompt_read_is_reused(model):
    client = FakeClient()
    extras_with_state = extras(client)
    extras_with_state[PROMPT_KEY] = {'state': {'content': 'old board', 'version': 3}, 'memories': []}
    app = make_app()

    await app.write_turn_memory(session_id='s1', source='TUI', session=finished_session(), extras=extras_with_state)

    assert client.state_reads == 0
    assert client.states[0]['version'] == 3


async def test_a_turn_without_a_cloud_is_a_no_op(model):
    app = make_app()
    await app.write_turn_memory(session_id='s1', source='TUI', session=finished_session(), extras=extras(None))
    await app.write_turn_memory(session_id='s1', source='TUI', session=finished_session(), extras=extras(FakeClient(), agent_id=None))
    await app.write_turn_memory(session_id='s1', source='TUI', session=finished_session())


async def test_the_flag_switches_it_off(model):
    client = FakeClient()
    app = make_app()
    app.auto_write_memory = False

    await app.write_turn_memory(session_id='s1', source='TUI', session=finished_session(), extras=extras(client))

    assert client.created == []


async def test_a_cloud_failure_never_escapes(model):
    client = FakeClient()
    client.fail = True
    app = make_app()

    await app.write_turn_memory(session_id='s1', source='TUI', session=finished_session(), extras=extras(client))


async def test_a_failing_writer_never_escapes(model, monkeypatch):
    async def explode(self, **kwargs):
        raise RuntimeError('writer bug')

    monkeypatch.setattr(writer_module.TurnMemoryWriter, 'write', explode)
    app = make_app()

    await app.write_turn_memory(session_id='s1', source='TUI', session=finished_session(), extras=extras(FakeClient()))


async def test_a_slow_write_is_cut_at_the_deadline(model, monkeypatch):
    seen: list[str] = []

    async def slow(self, **kwargs):
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            seen.append('cancelled')
            raise

    monkeypatch.setattr(writer_module.TurnMemoryWriter, 'write', slow)
    monkeypatch.setattr('rqark_app.app.TURN_MEMORY_TIMEOUT', 0.05)
    app = make_app()

    await asyncio.wait_for(app.write_turn_memory(session_id='s1', source='TUI', session=finished_session(), extras=extras(FakeClient())), 5)
    assert seen == ['cancelled']


async def test_a_cancelled_write_stays_cancelled(model, monkeypatch):
    async def pending(self, **kwargs):
        await asyncio.sleep(60)

    monkeypatch.setattr(writer_module.TurnMemoryWriter, 'write', pending)
    app = make_app()

    task = asyncio.create_task(app.write_turn_memory(session_id='s1', source='TUI', session=finished_session(), extras=extras(FakeClient())))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_the_drain_waits_for_the_last_write(model, monkeypatch):
    done: list[str] = []

    async def slow(self, **kwargs):
        await asyncio.sleep(0.05)
        done.append('written')

    monkeypatch.setattr(writer_module.TurnMemoryWriter, 'write', slow)
    app = make_app()

    task = asyncio.create_task(app.write_turn_memory(session_id='s1', source='TUI', session=finished_session(), extras=extras(FakeClient())))
    await asyncio.sleep(0)
    await app.drain_memory_writes(timeout=5)

    assert done == ['written']
    assert task.done()


async def test_the_drain_gives_up_after_its_deadline(model, monkeypatch):
    async def stuck(self, **kwargs):
        await asyncio.sleep(60)

    monkeypatch.setattr(writer_module.TurnMemoryWriter, 'write', stuck)
    app = make_app()

    task = asyncio.create_task(app.write_turn_memory(session_id='s1', source='TUI', session=finished_session(), extras=extras(FakeClient())))
    await asyncio.sleep(0)
    await app.drain_memory_writes(timeout=0.05)

    # Giving up on the deadline cancels the write: the loop is closing, so a
    # task left running would be dropped anyway, with a warning.
    assert task.cancelled()


async def test_the_drain_is_free_when_nothing_runs(model):
    app = make_app()
    await app.drain_memory_writes(timeout=0.01)
