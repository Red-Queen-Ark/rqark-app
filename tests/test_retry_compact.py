import asyncio

import httpx
import pytest
from openai import APIError
from rqark_core.types.chat import AssistantMessage
from rqark_core.types.provider import Provider

from rqark_app._app.helper import ChatHelper
from rqark_app.app import AgentApp
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


def make_provider(name: str, priority: int) -> Provider:
    return Provider('m', 'k', f'http://{name}', priority, name=name)


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
        if self.agent_id.startswith('Compact:'):
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
    monkeypatch.setattr('rqark_app._app.helper.AgentCore', ScriptedCore)
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
    assert compact.agent_id == 'Compact:abc'
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

    monkeypatch.setattr(app.chat_helper, 'get_summary', no_summary)
    session = await app.chat('hi', RetryAgent(), session_id='abc')
    main = scripted_core.instances[0]
    assert [[m.content for m in call[1]] for call in main.chat_calls] == [['hi'], ['hi']]
    assert [type(m).__name__ for m in session.history] == ['UserMessage', 'AssistantMessage']


def make_helper() -> ChatHelper:
    async def emit(*args, **kwargs) -> None:
        pass

    return ChatHelper(ProviderManager([make_provider('p1', 0)]), SessionManager(), emit)


def api_error(body: object, message: str = 'boom') -> APIError:
    return APIError(message, request=httpx.Request('POST', 'http://test'), body=body)


def test_is_context_overflow_detects_openai_message():
    helper = make_helper()
    assert helper.is_context_overflow(api_error(OVERFLOW_BODY)) is True
    assert helper.is_context_overflow(api_error({'error': {'message': 'Maximum Context Length reached'}})) is True


def test_is_context_overflow_rejects_other_errors():
    helper = make_helper()
    assert helper.is_context_overflow(api_error({'error': {'message': 'too many tokens'}})) is False
    assert helper.is_context_overflow(api_error(None)) is False
    assert helper.is_context_overflow(api_error('plain string body')) is False
    assert helper.is_context_overflow(api_error({'error': 'not a dict'})) is False
    assert helper.is_context_overflow(api_error({'error': {'message': 42}})) is False
    assert helper.is_context_overflow(RuntimeError('maximum context length')) is False
