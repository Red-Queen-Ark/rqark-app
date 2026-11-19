import asyncio
import json

import httpx
import pytest
from rqark_core.types.chat import UserMessage
from rqark_core.types.tool import PlanItem

from rqark_app.cloud.client import DataCloudError, RQArkDataCloudClient
from rqark_app.session.storage import CloudStorage
from rqark_app.types.cloud import CloudConfig
from rqark_app.types.session import Session, SummaryMessage

CREATED_AT = '2026-09-27T22:22:58+00:00'


class FakeCloud:
    def __init__(self):
        self.queued: dict[tuple[str, str], list[httpx.Response]] = {}
        self.calls: list[httpx.Request] = []

    def add(self, method: str, path: str, *responses: httpx.Response) -> None:
        self.queued[(method, path)] = list(responses)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        queued = self.queued.get((request.method, request.url.path))
        if not queued:
            return httpx.Response(404, json={'error': {'code': 'NOT_FOUND', 'message': 'not found'}})
        if len(queued) > 1:
            return queued.pop(0)
        return queued[0]


@pytest.fixture
async def cloud():
    fake = FakeCloud()
    client = RQArkDataCloudClient(CloudConfig(True, 'https://cloud.test', 'secret'), transport=httpx.MockTransport(fake.handler))
    fake.store = CloudStorage(client)
    yield fake
    await client.aclose()


def body(request: httpx.Request) -> dict:
    return json.loads(request.content)


def paths(cloud: FakeCloud) -> list[tuple[str, str]]:
    return [(request.method, request.url.path) for request in cloud.calls]


async def test_create_posts_the_metadata_without_history(cloud):
    cloud.add('POST', '/api/sessions', httpx.Response(201, json={'id': 's1'}))
    plan = [PlanItem('1', 'read the spec', 'in_progress')]
    session = Session(uuid='s1', title='spec', plan_items=plan)
    session.history = [UserMessage('hi')]

    await cloud.store.create(session)

    assert paths(cloud) == [('POST', '/api/sessions')]
    assert body(cloud.calls[0]) == {'uuid': 's1', 'title': 'spec', 'plan_items': [{'id': '1', 'content': 'read the spec', 'status': 'in_progress'}]}


async def test_save_updates_with_the_whole_history(cloud):
    cloud.add('PUT', '/api/sessions/s1', httpx.Response(200, json={'id': 's1'}))
    session = Session(uuid='s1', title='spec', history=[UserMessage('hi')])

    await cloud.store.save(session)

    assert paths(cloud) == [('PUT', '/api/sessions/s1')]
    sent = body(cloud.calls[0])
    assert sent['title'] == 'spec'
    assert sent['history'] == [{'role': 'user', 'content': [{'type': 'text', 'text': 'hi'}], 'created_at': session.history[0].to_dict()['created_at'], 'id': session.history[0].to_dict()['id']}]
    assert 'created_at' not in sent
    assert 'updated_at' not in sent


async def test_save_creates_a_session_the_cloud_does_not_have(cloud):
    cloud.add('PUT', '/api/sessions/s1', httpx.Response(404, json={'error': {'code': 'NOT_FOUND', 'message': 'Session not found.'}}), httpx.Response(200, json={'id': 's1'}))
    cloud.add('POST', '/api/sessions', httpx.Response(201, json={'id': 's1'}))
    session = Session(uuid='s1', title='spec', history=[UserMessage('hi')])

    await cloud.store.save(session)

    assert paths(cloud) == [('PUT', '/api/sessions/s1'), ('POST', '/api/sessions'), ('PUT', '/api/sessions/s1')]
    assert 'history' not in body(cloud.calls[1])
    assert body(cloud.calls[2])['history'][0]['role'] == 'user'


async def test_save_does_not_create_on_another_error(cloud):
    cloud.add('PUT', '/api/sessions/s1', httpx.Response(401, json={'error': {'code': 'UNAUTHORIZED', 'message': 'Invalid or revoked API key.'}}))

    with pytest.raises(DataCloudError) as info:
        await cloud.store.save(Session(uuid='s1'))

    assert info.value.code == 'UNAUTHORIZED'
    assert paths(cloud) == [('PUT', '/api/sessions/s1')]


async def test_load_restores_sessions_and_their_messages(cloud):
    metadata = {'id': 's1', 'title': 'spec', 'plan_items': [{'id': '1', 'content': 'a', 'status': 'pending'}], 'created_at': CREATED_AT, 'updated_at': CREATED_AT}
    cloud.add('GET', '/api/sessions', httpx.Response(200, json=[metadata]))
    cloud.add(
        'GET',
        '/api/sessions/s1/messages',
        httpx.Response(
            200,
            json=[
                {'seq': 0, 'role': 'user', 'data': {'role': 'user', 'content': [{'type': 'text', 'text': 'hi'}], 'created_at': CREATED_AT}, 'created_at': CREATED_AT},
                {'seq': 1, 'role': 'summary', 'data': {'role': 'summary', 'content': 'so far'}, 'created_at': None},
            ],
        ),
    )

    sessions = await cloud.store.load()

    assert len(sessions) == 1
    session = sessions[0]
    assert (session.uuid, session.title) == ('s1', 'spec')
    assert session.plan_items == [PlanItem('1', 'a', 'pending')]
    assert session.created_at.isoformat() == '2026-09-27T22:22:58+00:00'
    assert [type(message) for message in session.history] == [UserMessage, SummaryMessage]
    assert session.history[0].content == 'hi'
    assert session.history[1].content == 'so far'


async def test_load_keeps_the_message_ids(cloud):
    metadata = {'id': 's1', 'title': '', 'plan_items': [], 'created_at': CREATED_AT, 'updated_at': CREATED_AT}
    cloud.add('GET', '/api/sessions', httpx.Response(200, json=[metadata]))
    cloud.add(
        'GET',
        '/api/sessions/s1/messages',
        httpx.Response(
            200,
            json=[
                {'seq': 0, 'role': 'user', 'data': {'role': 'user', 'content': [{'type': 'text', 'text': 'hi'}], 'created_at': CREATED_AT, 'id': 'u1'}, 'created_at': CREATED_AT},
                {'seq': 1, 'role': 'summary', 'data': {'role': 'summary', 'content': 'so far', 'id': 's1-summary'}, 'created_at': None},
            ],
        ),
    )

    sessions = await cloud.store.load()

    assert [message.id for message in sessions[0].history] == ['u1', 's1-summary']


async def test_load_reads_both_lists_in_one_request_each(cloud):
    first = {'id': 's1', 'title': '', 'plan_items': [], 'created_at': CREATED_AT, 'updated_at': CREATED_AT}
    second = {'id': 's2', 'title': '', 'plan_items': [], 'created_at': CREATED_AT, 'updated_at': CREATED_AT}
    user = {'role': 'user', 'content': [{'type': 'text', 'text': 'hi'}], 'created_at': CREATED_AT}
    cloud.add('GET', '/api/sessions', httpx.Response(200, json=[first, second]))
    cloud.add('GET', '/api/sessions/s1/messages', httpx.Response(200, json=[{'seq': 0, 'role': 'user', 'data': user, 'created_at': CREATED_AT}]))
    cloud.add('GET', '/api/sessions/s2/messages', httpx.Response(200, json=[{'seq': 0, 'role': 'user', 'data': user, 'created_at': CREATED_AT}]))

    sessions = await cloud.store.load()

    assert [session.uuid for session in sessions] == ['s1', 's2']
    assert [len(session.history) for session in sessions] == [1, 1]
    assert paths(cloud) == [('GET', '/api/sessions'), ('GET', '/api/sessions/s1/messages'), ('GET', '/api/sessions/s2/messages')]
    assert all(not request.url.params for request in cloud.calls)


async def test_delete_reports_whether_the_session_was_there(cloud):
    cloud.add('DELETE', '/api/sessions/s1', httpx.Response(204), httpx.Response(404, json={'error': {'code': 'NOT_FOUND', 'message': 'Session not found.'}}))

    assert await cloud.store.delete('s1') is True
    assert await cloud.store.delete('s1') is False


async def test_delete_raises_on_another_error(cloud):
    cloud.add('DELETE', '/api/sessions/s1', httpx.Response(401, json={'error': {'code': 'UNAUTHORIZED', 'message': 'nope'}}))

    with pytest.raises(DataCloudError):
        await cloud.store.delete('s1')


async def test_a_source_is_stamped_on_every_write_without_restricting_the_listing():
    fake = FakeCloud()
    client = RQArkDataCloudClient(CloudConfig(True, 'https://cloud.test', 'secret'), transport=httpx.MockTransport(fake.handler))
    store = CloudStorage(client, source='TUI')
    fake.add('PUT', '/api/sessions/s1', httpx.Response(200, json={'id': 's1'}))
    fake.add('GET', '/api/sessions', httpx.Response(200, json=[]))

    try:
        await store.save(Session(uuid='s1'))
        await store.load()
    finally:
        await client.aclose()

    assert body(fake.calls[0])['source'] == 'TUI'
    assert not fake.calls[1].url.params


async def test_a_list_source_restricts_the_listing():
    fake = FakeCloud()
    client = RQArkDataCloudClient(CloudConfig(True, 'https://cloud.test', 'secret'), transport=httpx.MockTransport(fake.handler))
    store = CloudStorage(client, source='AGENT_CLOUD', list_source='AGENT_CLOUD')
    fake.add('PUT', '/api/sessions/s1', httpx.Response(200, json={'id': 's1'}))
    fake.add('GET', '/api/sessions', httpx.Response(200, json=[]))

    try:
        await store.save(Session(uuid='s1'))
        await store.load()
    finally:
        await client.aclose()

    assert body(fake.calls[0])['source'] == 'AGENT_CLOUD'
    assert fake.calls[1].url.params.get('source') == 'AGENT_CLOUD'


async def test_save_sends_the_agent_the_session_was_talked_to_with(cloud):
    cloud.add('PUT', '/api/sessions/s1', httpx.Response(200, json={'id': 's1'}))
    session = Session(uuid='s1', agent_id='agent-1')

    await cloud.store.save(session)

    assert body(cloud.calls[0])['agent_id'] == 'agent-1'


async def test_save_leaves_the_agent_out_when_the_session_names_none(cloud):
    cloud.add('PUT', '/api/sessions/s1', httpx.Response(200, json={'id': 's1'}))

    await cloud.store.save(Session(uuid='s1'))

    assert 'agent_id' not in body(cloud.calls[0])


async def test_load_restores_the_agent(cloud):
    metadata = {'id': 's1', 'title': '', 'agent_id': 'agent-1', 'plan_items': [], 'created_at': CREATED_AT, 'updated_at': CREATED_AT}
    cloud.add('GET', '/api/sessions', httpx.Response(200, json=[metadata]))
    cloud.add('GET', '/api/sessions/s1/messages', httpx.Response(200, json=[]))

    sessions = await cloud.store.load()

    assert sessions[0].agent_id == 'agent-1'


class CountingTransport(httpx.AsyncBaseTransport):
    """Records how many requests the client has in flight at the same time."""

    def __init__(self, handler, delay: float = 0.01) -> None:
        self._handler = handler
        self._delay = delay
        self.in_flight = 0
        self.peak = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        try:
            await asyncio.sleep(self._delay)
            return self._handler(request)
        finally:
            self.in_flight -= 1


async def test_load_fetches_session_messages_at_the_same_time():
    fake = FakeCloud()
    infos = [{'id': f's{index}', 'title': '', 'plan_items': [], 'created_at': CREATED_AT, 'updated_at': CREATED_AT} for index in range(4)]
    fake.add('GET', '/api/sessions', httpx.Response(200, json=infos))
    for info in infos:
        fake.add('GET', f'/api/sessions/{info["id"]}/messages', httpx.Response(200, json=[]))
    transport = CountingTransport(fake.handler)
    client = RQArkDataCloudClient(CloudConfig(True, 'https://cloud.test', 'secret'), transport=transport)

    try:
        sessions = await CloudStorage(client).load()
    finally:
        await client.aclose()

    assert [session.uuid for session in sessions] == [info['id'] for info in infos]
    assert transport.peak > 1


async def test_load_keeps_each_answer_with_its_session():
    fake = FakeCloud()
    infos = [{'id': f's{index}', 'title': '', 'plan_items': [], 'created_at': CREATED_AT, 'updated_at': CREATED_AT} for index in range(3)]
    fake.add('GET', '/api/sessions', httpx.Response(200, json=infos))
    for index, info in enumerate(infos):
        message = {'role': 'user', 'content': [{'type': 'text', 'text': f'hi {index}'}], 'created_at': CREATED_AT}
        fake.add('GET', f'/api/sessions/{info["id"]}/messages', httpx.Response(200, json=[{'seq': 0, 'role': 'user', 'data': message, 'created_at': CREATED_AT}]))
    client = RQArkDataCloudClient(CloudConfig(True, 'https://cloud.test', 'secret'), transport=httpx.MockTransport(fake.handler))

    try:
        sessions = await CloudStorage(client).load()
    finally:
        await client.aclose()

    assert [session.history[0].content for session in sessions] == ['hi 0', 'hi 1', 'hi 2']


async def test_load_can_be_limited_to_the_ids_it_is_given():
    fake = FakeCloud()
    infos = [{'id': f's{index}', 'title': '', 'plan_items': [], 'created_at': CREATED_AT, 'updated_at': CREATED_AT} for index in range(3)]
    fake.add('GET', '/api/sessions', httpx.Response(200, json=infos))
    fake.add('GET', '/api/sessions/s1/messages', httpx.Response(200, json=[]))
    client = RQArkDataCloudClient(CloudConfig(True, 'https://cloud.test', 'secret'), transport=httpx.MockTransport(fake.handler))

    try:
        sessions = await CloudStorage(client).load(['s1'])
    finally:
        await client.aclose()

    assert [session.uuid for session in sessions] == ['s1']
    assert paths(fake) == [('GET', '/api/sessions'), ('GET', '/api/sessions/s1/messages')]


async def test_load_with_no_ids_asks_the_cloud_nothing(cloud):
    assert await cloud.store.load([]) == []
    assert paths(cloud) == []


async def test_an_unknown_id_is_simply_absent():
    fake = FakeCloud()
    fake.add('GET', '/api/sessions', httpx.Response(200, json=[]))
    client = RQArkDataCloudClient(CloudConfig(True, 'https://cloud.test', 'secret'), transport=httpx.MockTransport(fake.handler))

    try:
        sessions = await CloudStorage(client).load(['gone'])
    finally:
        await client.aclose()

    assert sessions == []
    assert paths(fake) == [('GET', '/api/sessions')]
