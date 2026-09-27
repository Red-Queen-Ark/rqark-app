import json

import httpx
import pytest
from rqark_core.types.chat import UserMessage
from rqark_core.types.tool import PlanItem

from rqark_app.cloud.client import DataCloudError, RQArkDataCloudClient
from rqark_app.cloud.store import CloudStore
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
    fake.store = CloudStore(client)
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
    assert sent['history'] == [{'role': 'user', 'content': [{'type': 'text', 'text': 'hi'}], 'created_at': session.history[0].to_dict()['created_at']}]
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
