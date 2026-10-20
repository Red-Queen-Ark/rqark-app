import httpx
from openai import APIError
from rqark_core.types.chat import AssistantMessage, ToolMessage, UserMessage
from rqark_core.types.provider import Provider

from rqark_app.compact import Compactor, compact_messages
from rqark_app.provider.manager import ProviderManager
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


def make_helper(monkeypatch, max_messages=100) -> Compactor:
    FakeCompactCore.instances = []
    FakeCompactCore.max_messages = max_messages
    monkeypatch.setattr('rqark_app.compact.compactor.AgentCore', FakeCompactCore)
    return Compactor(ProviderManager([Provider('m', 'http://x', 0, 'k', name='p1')]))


def test_compact_messages_keeps_only_user_and_assistant_content():
    history = [
        UserMessage('u1'),
        AssistantMessage('a1', tool_calls=None, reasoning_content='think'),
        ToolMessage('c1', 'tool output', 'fn', '{}'),
        AssistantMessage('', tool_calls=None),
        UserMessage('   '),
        SummaryMessage('s1'),
        UserMessage('u2', images=['data:image/png;base64,xxxx']),
    ]
    compacted = compact_messages(history)
    assert [type(m).__name__ for m in compacted] == ['UserMessage', 'AssistantMessage', 'UserMessage', 'UserMessage']
    assert [m.content for m in compacted] == ['u1', 'a1', 's1', 'u2']
    first, last = compacted[0], compacted[-1]
    assert isinstance(first, UserMessage) and first.images == []
    assert isinstance(last, UserMessage) and last.images == []


async def test_get_summary_filters_tools_and_reasoning_before_calling_compact_core(monkeypatch):
    history = [UserMessage('u1'), AssistantMessage('a1', reasoning_content='think'), ToolMessage('c1', 'big tool output', 'fn', '{}'), SummaryMessage('s1'), UserMessage('u2'), AssistantMessage('a2'), UserMessage('u3')]
    helper = make_helper(monkeypatch)
    summary = await helper.get_summary(history)
    assert isinstance(summary, SummaryMessage)
    assert summary.content == 'SUMMARY'
    core = FakeCompactCore.instances[0]
    assert core.agent_id == 'Compact'
    assert [m.content for m in core.chat_calls[0]] == ['u1', 'a1', 's1', 'u2', 'a2', 'u3']
    assert not any(isinstance(m, ToolMessage) for m in core.chat_calls[0])
    assert core.chat_calls[0][1].reasoning_content is None
    assert core.chat_calls[0][1].tool_calls is None


async def test_get_summary_returns_none_for_empty_history(monkeypatch):
    helper = make_helper(monkeypatch)
    assert await helper.get_summary([]) is None
    assert FakeCompactCore.instances == []


async def test_get_summary_returns_none_when_history_has_no_ai_or_user_content(monkeypatch):
    helper = make_helper(monkeypatch)
    assert await helper.get_summary([ToolMessage('c1', 'output', 'fn', '{}')]) is None
    assert FakeCompactCore.instances == []


async def test_get_summary_trims_from_the_tail_then_retries(monkeypatch):
    history = [UserMessage('u1'), AssistantMessage('a1'), SummaryMessage('s1'), UserMessage('u2'), AssistantMessage('a2'), UserMessage('u3')]
    helper = make_helper(monkeypatch, max_messages=3)
    summary = await helper.get_summary(history)
    assert summary is not None
    core = FakeCompactCore.instances[0]
    assert [m.content for m in core.chat_calls[0]] == ['u1', 'a1', 's1', 'u2', 'a2', 'u3']
    assert [m.content for m in core.chat_calls[1]] == ['u1', 'a1', 's1', 'u2', 'a2']
    assert [m.content for m in core.chat_calls[-1]] == ['u1', 'a1', 's1']


async def test_get_summary_keeps_trimming_towards_the_tail_until_it_fits(monkeypatch):
    history = [UserMessage(f'u{i}') for i in range(8)]
    helper = make_helper(monkeypatch, max_messages=1)
    summary = await helper.get_summary(history)
    assert summary is not None
    core = FakeCompactCore.instances[0]
    assert [len(call) for call in core.chat_calls] == [8, 7, 6, 5, 4, 3, 2, 1]
    assert [m.content for m in core.chat_calls[-1]] == ['u0']


async def test_get_summary_returns_none_when_nothing_can_be_trimmed(monkeypatch):
    helper = make_helper(monkeypatch, max_messages=0)
    assert await helper.get_summary([UserMessage('big')]) is None
    assert len(FakeCompactCore.instances[0].chat_calls) == 1
