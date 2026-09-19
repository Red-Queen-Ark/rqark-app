from typing import cast

import httpx
import pytest
from openai import APIError
from rqark_core.types.chat import AssistantMessage, Message, UserMessage
from rqark_core.types.provider import Provider

from rqark_app.app import AgentApp
from rqark_app.session.manager import SessionManager
from rqark_app.session.storage import JSONLStorage
from rqark_app.types.agent import BaseAgent
from rqark_app.types.session import Session


class TestAgent(BaseAgent):
    name = 'wednesday'
    description = ''
    prompts = []
    tools = []


class FakeCore:
    instances: list['FakeCore'] = []
    errors = 0

    def __init__(self, agent_id: str = '', path: tuple[str, ...] = ()):
        self.agent_id = agent_id
        self.path = path
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
        if FakeCore.errors > 0:
            FakeCore.errors -= 1
            return messages, APIError('boom', request=httpx.Request('POST', 'http://test'), body=None)
        return [*messages, AssistantMessage('ok')], None


@pytest.fixture
def fake_core(monkeypatch):
    FakeCore.instances = []
    FakeCore.errors = 0
    monkeypatch.setattr('rqark_app.app.AgentCore', FakeCore)
    return FakeCore


def make_app(*providers) -> AgentApp:
    return AgentApp(list(providers))


def sent_history(core: FakeCore, index: int = 0) -> list[Message]:
    return cast('list[Message]', core.chat_calls[index][1])


def sent_user_message(core: FakeCore, index: int = 0) -> UserMessage:
    message = sent_history(core, index)[0]
    assert isinstance(message, UserMessage)
    return message


async def test_chat_attaches_images_to_user_message(fake_core):
    app = make_app(Provider('m', 'k', 'http://x', 0, name='p1'))
    events = []

    async def on_msg(ev):
        events.append(ev)

    app.on_message()(on_msg)
    await app.chat('look', TestAgent(), session_id='abc', images=['data:image/png;base64,AAA'])
    message = sent_user_message(fake_core.instances[0])
    assert message.content == 'look'
    assert message.images == ['data:image/png;base64,AAA']
    assert events[0].payload.images == ['data:image/png;base64,AAA']


async def test_chat_without_images_keeps_empty_list(fake_core):
    app = make_app(Provider('m', 'k', 'http://x', 0, name='p1'))
    await app.chat('hi', TestAgent(), session_id='abc')
    assert sent_user_message(fake_core.instances[0]).images == []


async def test_chat_accepts_images_without_text(fake_core):
    app = make_app(Provider('m', 'k', 'http://x', 0, name='p1'))
    await app.chat('', TestAgent(), session_id='abc', images=['data:image/png;base64,AAA'])
    message = sent_user_message(fake_core.instances[0])
    assert message.content == ''
    assert message.images == ['data:image/png;base64,AAA']
    assert message.to_dict()['content'] == [
        {'type': 'text', 'text': ''},
        {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,AAA'}},
    ]


async def test_chat_copies_caller_image_list(fake_core):
    app = make_app(Provider('m', 'k', 'http://x', 0, name='p1'))
    images = ['data:image/png;base64,AAA']
    await app.chat('look', TestAgent(), session_id='abc', images=images)
    images.append('data:image/png;base64,BBB')
    assert sent_user_message(fake_core.instances[0]).images == ['data:image/png;base64,AAA']


async def test_chat_replays_images_on_next_turn(fake_core):
    app = make_app(Provider('m', 'k', 'http://x', 0, name='p1'))
    await app.chat('look', TestAgent(), session_id='abc', images=['data:image/png;base64,AAA'])
    await app.chat('and now', TestAgent(), session_id='abc')
    history = sent_history(fake_core.instances[1])
    assert [m.content for m in history] == ['look', 'ok', 'and now']
    assert sent_user_message(fake_core.instances[1]).images == ['data:image/png;base64,AAA']


async def test_chat_persists_images_across_reload(fake_core, tmp_path):
    storage = JSONLStorage(tmp_path)
    app = AgentApp([Provider('m', 'k', 'http://x', 0, name='p1')], storage=storage)
    await app.chat('look', TestAgent(), session_id='abc', images=['data:image/png;base64,AAA'])
    mgr = SessionManager(storage)
    await mgr.load()
    message = next(m for m in mgr.sessions_map['abc'].history if isinstance(m, UserMessage))
    assert message.content == 'look'
    assert message.images == ['data:image/png;base64,AAA']
    assert message.to_dict()['content'] == [
        {'type': 'text', 'text': 'look'},
        {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,AAA'}},
    ]


async def test_chat_keeps_images_when_provider_retries(fake_core, monkeypatch):
    app = make_app(Provider('m1', 'k', 'http://a', 1, name='p1'), Provider('m2', 'k', 'http://b', 2, name='p2'))
    fake_core.errors = 1

    async def no_sleep(_):
        pass

    monkeypatch.setattr('asyncio.sleep', no_sleep)
    await app.chat('look', TestAgent(), session_id='abc', images=['data:image/png;base64,AAA'])
    core = fake_core.instances[0]
    assert len(core.chat_calls) == 2
    assert sent_user_message(core, -1).images == ['data:image/png;base64,AAA']


async def test_jsonl_storage_roundtrip_preserves_user_images(tmp_path):
    storage = JSONLStorage(tmp_path)
    session = Session(uuid='s1')
    user_msg = UserMessage('look', images=['data:image/png;base64,AAA', 'data:image/jpeg;base64,BBB'])
    session.history = [user_msg, AssistantMessage('yo')]
    await storage.create(session)
    s = (await storage.load())[0]
    assert isinstance(s.history[0], UserMessage)
    assert s.history[0].content == 'look'
    assert s.history[0].images == ['data:image/png;base64,AAA', 'data:image/jpeg;base64,BBB']
    assert s.history[0].created_at == user_msg.created_at
    assert s.history[0].to_dict() == user_msg.to_dict()


async def test_jsonl_storage_keeps_legacy_string_user_content(tmp_path):
    file = tmp_path / 'legacy.jsonl'
    file.write_text(
        '\n'.join([
            '{"uuid": "legacy", "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00", "title": "", "plan_items": []}',
            '{"role": "user", "content": "hi"}',
        ]) + '\n',
        encoding='utf-8',
    )
    s = (await JSONLStorage(tmp_path).load())[0]
    assert isinstance(s.history[0], UserMessage)
    assert s.history[0].content == 'hi'
    assert s.history[0].images == []


async def test_jsonl_storage_separates_multiple_text_parts(tmp_path):
    file = tmp_path / 'multi.jsonl'
    file.write_text(
        '\n'.join([
            '{"uuid": "multi", "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00", "title": "", "plan_items": []}',
            '{"role": "user", "content": [{"type": "text", "text": "a"}, {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA"}}, {"type": "text", "text": "b"}]}',
        ]) + '\n',
        encoding='utf-8',
    )
    s = (await JSONLStorage(tmp_path).load())[0]
    assert isinstance(s.history[0], UserMessage)
    assert s.history[0].content == 'a\nb'
    assert s.history[0].images == ['data:image/png;base64,AAA']


async def test_jsonl_storage_ignores_malformed_user_parts(tmp_path):
    file = tmp_path / 'malformed.jsonl'
    file.write_text(
        '\n'.join([
            '{"uuid": "malformed", "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00", "title": "", "plan_items": []}',
            '{"role": "user", "content": ["text", {"type": "text", "text": null}, {"type": "text", "text": "kept"}, {"type": "image_url", "image_url": "data:image/png;base64,AAA"}, {"type": "image_url", "image_url": {"url": 1}}, {"type": "image_url", "image_url": {"url": "data:image/png;base64,BBB"}}, {"type": "audio", "text": "x"}]}',
        ])
        + '\n',
        encoding='utf-8',
    )
    s = (await JSONLStorage(tmp_path).load())[0]
    assert isinstance(s.history[0], UserMessage)
    assert s.history[0].content == 'kept'
    assert s.history[0].images == ['data:image/png;base64,BBB']


async def test_jsonl_storage_handles_non_string_non_list_user_content(tmp_path):
    file = tmp_path / 'scalar.jsonl'
    file.write_text(
        '\n'.join([
            '{"uuid": "scalar", "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00", "title": "", "plan_items": []}',
            '{"role": "user", "content": 42}',
        ])
        + '\n',
        encoding='utf-8',
    )
    s = (await JSONLStorage(tmp_path).load())[0]
    assert isinstance(s.history[0], UserMessage)
    assert s.history[0].content == ''
    assert s.history[0].images == []
