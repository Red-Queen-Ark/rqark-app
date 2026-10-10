from rqark_core.types.chat import AssistantMessage, ToolMessage, UserMessage

from rqark_app.session.storage import JSONLStorage
from rqark_app.types.session import Session, SummaryMessage, message_from_dict


def ids(messages) -> list[str]:
    return [message.id for message in messages]


def test_message_from_dict_keeps_the_id():
    message = message_from_dict({'role': 'user', 'content': 'hi', 'id': 'u1', 'created_at': '2026-01-01T00:00:00+00:00'})

    assert message.id == 'u1'


def test_message_from_dict_generates_an_id_for_legacy_payloads():
    first = message_from_dict({'role': 'user', 'content': 'hi'})
    second = message_from_dict({'role': 'user', 'content': 'hi'})

    assert first.id and second.id and first.id != second.id


def test_every_message_role_round_trips_its_id():
    raw = [
        {'role': 'user', 'content': 'hi', 'id': 'u1'},
        {'role': 'assistant', 'content': 'yo', 'id': 'a1'},
        {'role': 'tool', 'tool_call_id': 'c1', 'content': 'out', 'id': 't1'},
        {'role': 'system', 'content': 'sys', 'id': 's1'},
        {'role': 'summary', 'content': 'so far', 'id': 'm1'},
    ]

    assert ids([message_from_dict(item) for item in raw]) == ['u1', 'a1', 't1', 's1', 'm1']


async def test_jsonl_storage_roundtrip_preserves_every_id(tmp_path):
    session = Session(uuid='s1')
    session.history = [UserMessage('hi'), AssistantMessage('yo'), ToolMessage('c1', 'out'), SummaryMessage('so far')]
    storage = JSONLStorage(tmp_path)

    await storage.create(session)
    loaded = (await storage.load())[0]

    assert ids(loaded.history) == ids(session.history)
    assert [message.to_dict() for message in loaded.history] == [message.to_dict() for message in session.history]


def test_revert_drops_everything_after_the_target_user_message():
    first, second = UserMessage('one'), UserMessage('two')
    history = [first, AssistantMessage('a1'), second, AssistantMessage('a2')]
    session = Session(history=list(history))

    removed = session.revert_to(second.id)

    assert removed == [history[3]]
    assert session.history == history[:3]


def test_revert_keeps_the_target_user_message_only_even_mid_chunk():
    first, second, assistant = UserMessage('one'), UserMessage('two'), AssistantMessage('a2')
    session = Session(history=[first, second, assistant])

    assert session.revert_to(second.id) == [assistant]
    assert session.history == [first, second]


def test_revert_is_refused_with_a_single_user_message():
    user, assistant = UserMessage('one'), AssistantMessage('a1')
    session = Session(history=[user, assistant])

    assert session.revert_to(user.id) is None
    assert session.history == [user, assistant]


def test_revert_is_refused_for_an_unknown_or_non_user_message():
    user, assistant = UserMessage('one'), AssistantMessage('a1')
    session = Session(history=[user, assistant])

    assert session.revert_to('missing') is None
    assert session.revert_to(assistant.id) is None
    assert session.history == [user, assistant]


def test_revert_never_touches_an_earlier_chunk():
    first, second = UserMessage('one'), UserMessage('two')
    summary = SummaryMessage('so far')
    history = [first, AssistantMessage('a1'), summary, second, AssistantMessage('a2')]
    session = Session(history=list(history))

    assert session.revert_to(second.id) == [history[4]]
    assert session.history == history[:4]

    assert session.revert_to(first.id) is not None
    assert session.history == [first]
