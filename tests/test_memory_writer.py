import json

import pytest
from rqark_core.types.chat import AssistantMessage, ToolCall, ToolMessage, UserMessage

from rqark_app.cloud.client import DataCloudError
from rqark_app.memory import writer as writer_module
from rqark_app.memory.writer import TurnMemoryWriter, parse_answer, row_entries, should_skip, tool_note, turn_from_session
from rqark_app.types.session import Session


class FakeClient:
    def __init__(self) -> None:
        self.created: list[dict] = []
        self.states: list[dict] = []
        self.state_reads = 0
        self.conflict_once = False
        self.state = {'content': 'old board', 'version': 3}

    async def create_memory(self, payload: dict) -> dict:
        if not payload.get('occurred_at'):
            raise DataCloudError(400, 'INVALID_CONTENT', 'occurred_at is required.')
        self.created.append(payload)
        return {'id': 'memory-1'}

    async def set_state(self, agent_id: str, content: str, source: str, version: int | None = None) -> dict:
        if self.conflict_once:
            self.conflict_once = False
            raise DataCloudError(409, 'STATE_CONFLICT', 'someone else wrote it')
        self.states.append({'agent_id': agent_id, 'content': content, 'source': source, 'version': version})
        return {'version': (version or 0) + 1}

    async def get_state(self, agent_id: str) -> dict | None:
        self.state_reads += 1
        return self.state


class FakeProviderMgr:
    provider = None


@pytest.fixture
def model(monkeypatch):
    """Stub the writer's own AgentCore, the way the compactor is stubbed."""

    class FakeCore:
        answer = ''
        error: Exception | None = None
        calls: list = []

        def __init__(self, agent_id: str = '', path=(), extras=None):
            self.agent_id = agent_id

        async def chat(self, provider, messages, prompts, tools):
            FakeCore.calls.append((provider, messages, prompts, tools))
            if FakeCore.error is not None:
                return [*messages], FakeCore.error
            return [*messages, AssistantMessage(FakeCore.answer)], None

    FakeCore.calls = []
    monkeypatch.setattr(writer_module, 'AgentCore', FakeCore)
    return FakeCore


def writer(client: FakeClient) -> TurnMemoryWriter:
    return TurnMemoryWriter(FakeProviderMgr(), client)


async def write(client: FakeClient, **kwargs) -> None:
    params = {
        'agent_id': 'agent-1',
        'source': 'TUI',
        'user_text': 'Boss 叫 agent 修好 memory writer',
        'assistant_text': 'x' * 400,
        'tool_calls': ['exec python -m pytest'],
        'session_id': 'session-1',
        'current_state': {'content': 'old board', 'version': 3},
    }
    params.update(kwargs)
    await writer(client).write(**params)


ANSWER = {'skip': False, 'state': '## Now\n- memory writer 寫好', 'events': [{'content': 'Boss 叫 agent 修好 memory writer；agent 改咗 writer.py', 'keywords': ['memory', 'writer']}], 'facts': []}


async def test_the_turn_is_written_as_one_event_and_the_new_state(model):
    model.answer = json.dumps(ANSWER, ensure_ascii=False)
    client = FakeClient()
    await write(client)

    assert [row['kind'] for row in client.created] == ['event']
    assert client.created[0]['content'] == 'Boss 叫 agent 修好 memory writer；agent 改咗 writer.py'
    assert client.created[0]['source'] == 'TUI'
    assert client.created[0]['keywords'] == ['memory', 'writer']
    assert client.created[0]['occurred_at']

    assert len(client.states) == 1
    assert client.states[0]['content'] == '## Now\n- memory writer 寫好'
    assert client.states[0]['version'] == 3
    assert client.states[0]['source'] == 'TUI'


async def test_the_model_is_asked_once_in_its_own_core(model):
    model.answer = json.dumps(ANSWER, ensure_ascii=False)
    await write(FakeClient())

    assert len(model.calls) == 1
    _, messages, prompts, tools = model.calls[0]
    assert tools == []
    assert len(prompts) == 1
    request = json.loads(messages[0].content)
    assert request['current_state'] == 'old board'
    assert request['user_message'] == 'Boss 叫 agent 修好 memory writer'
    assert request['tool_calls'] == ['exec python -m pytest']


async def test_a_skip_answer_writes_nothing(model):
    model.answer = json.dumps({'skip': True, 'state': '', 'events': [], 'facts': []})
    client = FakeClient()
    await write(client)
    assert client.created == []
    assert client.states == []


async def test_a_tasks_turn_keeps_its_event_but_not_the_state(model):
    model.answer = json.dumps(ANSWER, ensure_ascii=False)
    client = FakeClient()
    await write(client, allow_state_update=False)

    assert len(client.created) == 1
    assert client.states == []


async def test_facts_are_written_as_facts(model):
    model.answer = json.dumps({**ANSWER, 'facts': [{'content': 'Boss 用 UTC+8', 'keywords': ['timezone']}]}, ensure_ascii=False)
    client = FakeClient()
    await write(client)
    assert [row['kind'] for row in client.created] == ['event', 'fact']


async def test_small_talk_never_costs_a_model_call(model):
    model.answer = json.dumps(ANSWER)
    client = FakeClient()
    await write(client, user_text='喂', assistant_text='你好，Boss。', tool_calls=[])
    assert model.calls == []
    assert client.created == []


async def test_a_short_turn_with_a_tool_is_still_considered(model):
    model.answer = json.dumps(ANSWER, ensure_ascii=False)
    client = FakeClient()
    await write(client, user_text='跑測試', assistant_text='過了。', tool_calls=['exec pytest'])
    assert len(model.calls) == 1
    assert len(client.created) == 1


async def test_an_empty_user_message_is_not_a_turn(model):
    model.answer = json.dumps(ANSWER)
    await write(FakeClient(), user_text='   ')
    assert model.calls == []


async def test_a_model_error_writes_nothing(model):
    model.error = RuntimeError('provider down')
    client = FakeClient()
    await write(client)
    assert client.created == []
    assert client.states == []


async def test_a_broken_answer_writes_nothing(model):
    model.answer = 'I could not do that, sorry.'
    client = FakeClient()
    await write(client)
    assert client.created == []
    assert client.states == []


async def test_a_fenced_answer_is_read(model):
    model.answer = '```json\n' + json.dumps(ANSWER, ensure_ascii=False) + '\n```'
    client = FakeClient()
    await write(client)
    assert len(client.created) == 1


async def test_a_conflict_is_retried_once_with_the_fresh_version(model):
    model.answer = json.dumps(ANSWER, ensure_ascii=False)
    client = FakeClient()
    client.state = {'content': 'newer board', 'version': 9}
    client.conflict_once = True
    await write(client)

    assert client.state_reads == 1
    assert len(client.states) == 1
    assert client.states[0]['version'] == 9


async def test_an_over_long_state_keeps_the_old_board(model):
    model.answer = json.dumps({**ANSWER, 'state': 'x' * 2001}, ensure_ascii=False)
    client = FakeClient()
    await write(client)
    assert client.states == []
    assert len(client.created) == 1


async def test_a_blank_state_is_not_written(model):
    model.answer = json.dumps({**ANSWER, 'state': '   '}, ensure_ascii=False)
    client = FakeClient()
    await write(client)
    assert client.states == []


def test_should_skip_covers_the_cheap_cases():
    assert should_skip('', 'anything', [])
    assert should_skip('喂', '你好', [])
    assert not should_skip('喂', 'x' * 400, [])
    assert not should_skip('跑測試', 'passed', ['exec pytest'])


def test_parse_answer_survives_text_around_the_object():
    assert parse_answer('sure:\n{"skip": false, "events": []}\nthat is all') == {'skip': False, 'events': []}
    assert parse_answer('not json') == {}
    assert parse_answer('[1, 2]') == {}


def test_row_entries_clamps_and_drops_empty_rows():
    rows = [{'content': 'x' * 250, 'keywords': ['a', ' ', 'b']}, {'content': '  '}, {'content': 5}, 'nonsense', {'content': 'ok', 'keywords': 'not a list'}]
    assert row_entries(rows, kind='event') == [('x' * 200, ['a', 'b']), ('ok', [])]


def test_row_entries_caps_keywords_at_eight():
    rows = [{'content': 'ok', 'keywords': [str(i) for i in range(12)]}]
    assert row_entries(rows, kind='event') == [('ok', [str(i) for i in range(8)])]


def test_turn_from_session_collects_the_last_turn_only():
    session = Session()
    session.history = [
        UserMessage('earlier question'),
        AssistantMessage('earlier answer'),
        UserMessage('Boss 叫 agent 修好 writer'),
        AssistantMessage('', tool_calls=[ToolCall('c1', 'function', 'exec', '{"command": "pytest -q"}')]),
        ToolMessage('c1', 'output', tool_name='exec'),
        AssistantMessage('改好咗，測試過。'),
    ]

    user_text, assistant_text, notes = turn_from_session(session)

    assert user_text == 'Boss 叫 agent 修好 writer'
    assert assistant_text == '改好咗，測試過。'
    assert notes == ['exec {"command": "pytest -q"}']


def test_turn_from_session_handles_an_answer_without_tools():
    session = Session()
    session.history = [UserMessage('hello'), AssistantMessage('hi')]
    assert turn_from_session(session) == ('hello', 'hi', [])


def test_tool_note_is_one_collapsed_line():
    assert tool_note('exec', 'line one\n  line two') == 'exec line one line two'
    assert tool_note('list_dir', '') == 'list_dir'
    assert tool_note('read_file', 'x' * 300).endswith('…')
