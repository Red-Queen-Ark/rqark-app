import asyncio

import httpx
import pytest
from openai import APIError
from rqark_core.types.chat import AssistantMessage, ToolMessage, Usage, UserMessage
from rqark_core.types.provider import Provider

from rqark_app.app import AgentApp
from rqark_app.compact import Compactor, is_context_overflow
from rqark_app.provider.manager import ProviderManager
from rqark_app.session.manager import SessionManager
from rqark_app.session.storage import JSONLStorage
from rqark_app.types.agent import BaseAgent
from rqark_app.types.session import SummaryMessage


class RetryAgent(BaseAgent):
    name = 'wednesday'
    description = ''
    prompts = []
    tools = []


OVERFLOW_BODY = {'error': {'message': "This model's maximum context length is 8192 tokens"}}


def make_provider(name: str, priority: int, model: str = 'm') -> Provider:
    return Provider(model, 'k', f'http://{name}', priority, name=name)


class ScriptedCore:
    instances: list['ScriptedCore'] = []
    api_errors = 0
    overflow_errors = 0
    summary = 'SUMMARY'

    def __init__(self, agent_id: str = '', path: tuple[str, ...] = ()):
        self.agent_id = agent_id
        self.path = path
        self.chat_calls: list[tuple] = []
        ScriptedCore.instances.append(self)

    def on_chunk(self):
        return lambda f: f

    def on_message(self):
        return lambda f: f

    def on_plan(self):
        return lambda f: f

    async def chat(self, provider, messages, prompts, tools):
        self.chat_calls.append((provider, list(messages), prompts, tools))
        if self.agent_id.startswith('Compact'):
            return [*messages, AssistantMessage(ScriptedCore.summary)], None
        request = httpx.Request('POST', 'http://test')
        if ScriptedCore.overflow_errors > 0:
            ScriptedCore.overflow_errors -= 1
            return list(messages), APIError('too long', request=request, body=OVERFLOW_BODY)
        if ScriptedCore.api_errors > 0:
            ScriptedCore.api_errors -= 1
            return list(messages), APIError('boom', request=request, body=None)
        return [*messages, AssistantMessage('ok')], None


@pytest.fixture
def scripted_core(monkeypatch):
    ScriptedCore.instances = []
    ScriptedCore.api_errors = 0
    ScriptedCore.overflow_errors = 0
    ScriptedCore.summary = 'SUMMARY'
    monkeypatch.setattr('rqark_app.app.AgentCore', ScriptedCore)
    monkeypatch.setattr('rqark_app.compact.compactor.AgentCore', ScriptedCore)
    return ScriptedCore


@pytest.fixture
def instant_sleep(monkeypatch):
    async def no_sleep(_):
        pass

    monkeypatch.setattr(asyncio, 'sleep', no_sleep)


async def test_api_error_retries_with_unchanged_history_until_success(scripted_core, instant_sleep):
    scripted_core.api_errors = 2
    app = AgentApp([make_provider('p1', 0)])
    session = await app.chat('hi', RetryAgent(), session_id='abc')
    core = scripted_core.instances[0]
    assert [[m.content for m in call[1]] for call in core.chat_calls] == [['hi'], ['hi'], ['hi']]
    assert len(scripted_core.instances) == 1
    assert [type(m).__name__ for m in session.history] == ['UserMessage', 'AssistantMessage']
    assert session.history[-1].content == 'ok'


async def test_retry_keeps_going_after_exhausting_every_provider(scripted_core, instant_sleep):
    scripted_core.api_errors = 12
    app = AgentApp([make_provider('p1', 0), make_provider('p2', 1)])
    switches = []

    async def on_switch(ev):
        switches.append((ev.payload.old.name, ev.payload.new.name))

    app.on_provider_switched()(on_switch)
    await app.chat('hi', RetryAgent(), session_id='abc')
    core = scripted_core.instances[0]
    used = [call[0].name for call in core.chat_calls]
    assert len(used) == 13
    assert set(used) == {'p1', 'p2'}
    assert used[-1] == 'p1'
    assert switches == [('p1', 'p2'), ('p2', 'p1'), ('p1', 'p2'), ('p2', 'p1')]


async def test_retry_never_gives_up_on_persistent_errors(scripted_core, monkeypatch):
    real_sleep = asyncio.sleep

    async def yield_sleep(_):
        await real_sleep(0)

    monkeypatch.setattr(asyncio, 'sleep', yield_sleep)
    scripted_core.api_errors = 10**9
    app = AgentApp([make_provider('p1', 0), make_provider('p2', 1)])
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(app.chat('hi', RetryAgent(), session_id='abc'), timeout=0.05)
    core = scripted_core.instances[0]
    assert len(core.chat_calls) > 10
    assert {call[0].name for call in core.chat_calls} == {'p1', 'p2'}


async def test_context_overflow_compacts_and_retries_with_only_the_summary(scripted_core, instant_sleep, tmp_path):
    scripted_core.overflow_errors = 1
    app = AgentApp([make_provider('p1', 0)], storage=JSONLStorage(tmp_path))
    session = await app.chat('hi', RetryAgent(), session_id='abc')
    main, compact = scripted_core.instances
    assert compact.agent_id == 'Compact'
    assert [[m.content for m in call[1]] for call in compact.chat_calls] == [['hi']]
    assert [[m.content for m in call[1]] for call in main.chat_calls] == [['hi'], ['SUMMARY']]
    assert [type(m).__name__ for m in session.history] == ['UserMessage', 'SummaryMessage', 'AssistantMessage']
    assert isinstance(session.history[1], SummaryMessage)
    assert session.history[1].content == 'SUMMARY'
    reloaded = SessionManager(JSONLStorage(tmp_path))
    await reloaded.load()
    assert [type(m).__name__ for m in reloaded.sessions_map['abc'].history] == ['UserMessage', 'SummaryMessage', 'AssistantMessage']


async def test_context_overflow_retries_original_history_when_summary_unavailable(scripted_core, instant_sleep, monkeypatch):
    scripted_core.overflow_errors = 1
    app = AgentApp([make_provider('p1', 0)])

    async def no_summary(_):
        return None

    monkeypatch.setattr(app.compactor, 'get_summary', no_summary)
    session = await app.chat('hi', RetryAgent(), session_id='abc')
    main = scripted_core.instances[0]
    assert [[m.content for m in call[1]] for call in main.chat_calls] == [['hi'], ['hi']]
    assert [type(m).__name__ for m in session.history] == ['UserMessage', 'AssistantMessage']


async def test_proactive_compression_triggers_on_last_usage_before_calling_the_model(scripted_core, instant_sleep):
    scripted_core.overflow_errors = 0
    app = AgentApp([make_provider('p1', 0, model='gpt-4o')])
    session = await app.session_mgr.create('abc')
    session.history = [UserMessage('u1'), AssistantMessage('a1', usage=Usage(120_000, 10, 120_010))]
    await app.chat('u2', RetryAgent(), session_id='abc')
    main, compact = scripted_core.instances
    assert compact.agent_id == 'Compact'
    assert [[m.content for m in call[1]] for call in compact.chat_calls] == [['u1', 'a1']]
    assert [[m.content for m in call[1]] for call in main.chat_calls] == [['SUMMARY', 'u2']]
    assert [type(m).__name__ for m in session.history] == ['UserMessage', 'AssistantMessage', 'SummaryMessage', 'UserMessage', 'AssistantMessage']


async def test_proactive_compression_skipped_when_usage_is_below_ratio(scripted_core, instant_sleep):
    app = AgentApp([make_provider('p1', 0, model='gpt-4o')])
    session = await app.session_mgr.create('abc')
    session.history = [UserMessage('u1'), AssistantMessage('a1', usage=Usage(10_000, 10, 10_010))]
    await app.chat('u2', RetryAgent(), session_id='abc')
    assert len(scripted_core.instances) == 1
    core = scripted_core.instances[0]
    assert [[m.content for m in call[1]] for call in core.chat_calls] == [['u1', 'a1', 'u2']]


async def test_proactive_compression_ignores_tool_only_usage(scripted_core, instant_sleep):
    app = AgentApp([make_provider('p1', 0, model='gpt-4o')])
    session = await app.session_mgr.create('abc')
    session.history = [UserMessage('u1'), AssistantMessage('a1', usage=None), ToolMessage('c1', 'output', 'fn', '{}')]
    await app.chat('u2', RetryAgent(), session_id='abc')
    assert len(scripted_core.instances) == 1


def make_helper() -> Compactor:
    return Compactor(ProviderManager([make_provider('p1', 0)]))


def api_error(body: object, message: str = 'boom') -> APIError:
    return APIError(message, request=httpx.Request('POST', 'http://test'), body=body)


def test_needs_compression_uses_latest_usage_of_the_provider_window():
    helper = make_helper()
    provider = make_provider('p1', 0, model='gpt-4o')
    below = [AssistantMessage('a', usage=Usage(100_000, 1, 100_001))]
    above = [AssistantMessage('a', usage=Usage(115_200, 1, 115_201))]
    assert helper.needs_compression(below, provider) is False
    assert helper.needs_compression(above, provider) is True
    assert helper.needs_compression([UserMessage('u')], provider) is False


def test_needs_compression_uses_the_most_recent_usage():
    helper = make_helper()
    provider = make_provider('p1', 0, model='gpt-4o')
    messages = [AssistantMessage('old', usage=Usage(200_000, 1, 200_001)), UserMessage('u'), AssistantMessage('new', usage=Usage(1_000, 1, 1_001))]
    assert helper.needs_compression(messages, provider) is False


def test_is_context_overflow_detects_reported_provider_messages():
    assert is_context_overflow(api_error(OVERFLOW_BODY)) is True
    assert is_context_overflow(api_error({'error': {'message': 'Maximum Context Length reached'}})) is True
    assert is_context_overflow(api_error({'error': {'message': 'Your request exceeded model token limit: 1048576 (requested: 1705112)'}})) is True
    assert is_context_overflow(api_error({'error': {'code': 'InvalidParameter', 'message': 'Input exceeds the context limit (1048568 tokens). Please shorten the input.'}})) is True
    assert is_context_overflow(api_error({'error': {'code': 'context_length_exceeded', 'message': 'nope'}})) is True
    assert is_context_overflow(api_error({'error': {'message': 'too many tokens'}})) is True
    assert is_context_overflow(api_error({'error': 'prompt is too long'}, message='prompt is too long')) is True


def test_is_context_overflow_detects_413_status():
    class OversizedError(APIError):
        status_code = 413

    error = OversizedError('too large', request=httpx.Request('POST', 'http://test'), body=None)
    assert is_context_overflow(error) is True


def test_is_context_overflow_rejects_other_errors():
    assert is_context_overflow(api_error({'error': {'message': 'rate limit reached'}})) is False
    assert is_context_overflow(api_error({'error': {'message': 'Too Many Requests'}})) is False
    assert is_context_overflow(api_error(None)) is False
    assert is_context_overflow(api_error('plain string body')) is False
    assert is_context_overflow(api_error({'error': 'not a dict'})) is False
    assert is_context_overflow(api_error({'error': {'message': 42}})) is False
    assert is_context_overflow(RuntimeError('maximum context length')) is False
