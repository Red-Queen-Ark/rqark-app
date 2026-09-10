import httpx
from openai import APIError
from rqark_core.types.chat import AssistantMessage, UserMessage
from rqark_core.types.provider import Provider

from rqark_app._app.helper import ChatHelper
from rqark_app.provider.manager import ProviderManager
from rqark_app.session.manager import SessionManager
from rqark_app.types.session import SummaryMessage


class FakeCompactCore:
    instances: list['FakeCompactCore'] = []
    max_messages = 100

    def __init__(self, agent_id: str = '', path: tuple[str, ...] = ()):
        self.agent_id = agent_id
        self.path = path
        self.chat_calls: list[list] = []
        FakeCompactCore.instances.append(self)

    async def chat(self, provider, messages, prompts, tools):
        self.chat_calls.append(list(messages))
        if len(messages) > FakeCompactCore.max_messages:
            request = httpx.Request('POST', 'http://test')
            return list(messages), APIError('too long', request=request, body={'error': {'message': 'maximum context length'}})
        return [*messages, AssistantMessage('SUMMARY')], None


async def _emit(*args, **kwargs) -> None:
    pass


async def make_helper(monkeypatch, history, max_messages=100):
    FakeCompactCore.instances = []
    FakeCompactCore.max_messages = max_messages
    monkeypatch.setattr('rqark_app._app.helper.AgentCore', FakeCompactCore)
    helper = ChatHelper(ProviderManager([Provider('m', 'k', 'http://x', 0, name='p1')]), SessionManager(), _emit)
    session = await helper.session_mgr.create('abc')
    session.history = history
    return helper


async def test_get_summary_feeds_last_chunk_with_prior_summary_and_latest_user(monkeypatch):
    history = [
        UserMessage('u1'),
        AssistantMessage('a1'),
        SummaryMessage('s1'),
        UserMessage('u2'),
        AssistantMessage('a2', reasoning_content='think'),
        UserMessage('u3'),
    ]
    helper = await make_helper(monkeypatch, history)
    summary = await helper.get_summary('abc')
    assert isinstance(summary, SummaryMessage)
    assert summary.content == 'SUMMARY'
    core = FakeCompactCore.instances[0]
    assert core.agent_id == 'Compact:abc'
    assert [m.content for m in core.chat_calls[0]] == ['s1', 'u2', 'a2', 'u3']
    assert core.chat_calls[0][2].reasoning_content is None


async def test_get_summary_returns_none_for_unknown_session(monkeypatch):
    helper = await make_helper(monkeypatch, [])
    assert await helper.get_summary('missing') is None


async def test_get_summary_falls_back_to_head_and_tail_when_compact_overflows(monkeypatch):
    history = [
        UserMessage('u1'),
        AssistantMessage('a1'),
        SummaryMessage('s1'),
        UserMessage('u2'),
        AssistantMessage('a2'),
        UserMessage('u3'),
    ]
    helper = await make_helper(monkeypatch, history, max_messages=3)
    summary = await helper.get_summary('abc')
    assert summary is not None
    core = FakeCompactCore.instances[0]
    assert [m.content for m in core.chat_calls[0]] == ['s1', 'u2', 'a2', 'u3']
    assert [m.content for m in core.chat_calls[1]] == ['s1', 'u3']


async def test_get_summary_returns_none_when_nothing_can_be_trimmed(monkeypatch):
    helper = await make_helper(monkeypatch, [UserMessage('big')], max_messages=0)
    assert await helper.get_summary('abc') is None
    assert len(FakeCompactCore.instances[0].chat_calls) == 1
