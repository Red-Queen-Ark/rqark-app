import json
from typing import Any

from rqark_core.types.tool import ToolContext

from rqark_app.tools import Todo
from rqark_app.tools.context import CLIENT_KEY

TODO = {
    'id': '5c9d3b1e-1a1a-4a1a-8a1a-1a1a1a1a1a1a',
    'title': '寫 issue',
    'description': '',
    'done': False,
    'done_at': None,
    'due_at': '2026-10-20T09:00:00Z',
    'sort_order': 0,
}


class FakeClient:
    def __init__(self) -> None:
        self.todos: list[dict] = [TODO]
        self.listed: list[bool | None] = []
        self.created: list[dict] = []
        self.updated: list[tuple[str, dict]] = []
        self.deleted: list[str] = []

    async def list_todos(self, done: bool | None = None) -> list[dict]:
        self.listed.append(done)
        return self.todos

    async def create_todo(self, payload: dict) -> dict:
        self.created.append(payload)
        return {**TODO, 'id': 'new', **payload}

    async def update_todo(self, uuid: str, payload: dict) -> dict:
        self.updated.append((uuid, payload))
        return {**TODO, 'id': uuid, **payload}

    async def delete_todo(self, uuid: str) -> None:
        self.deleted.append(uuid)


def context(client: FakeClient | None = None, **extra: Any) -> ToolContext:
    extras: dict[str, Any] = dict(extra)
    if client is not None:
        extras[CLIENT_KEY] = client
    return ToolContext(extras=extras)


async def test_list_returns_the_todos_with_the_stable_keys():
    client = FakeClient()
    result = await Todo().run(ctx=context(client), action='list')
    assert json.loads(result) == [TODO]
    assert client.listed == [None]


async def test_list_passes_the_done_filter_as_a_bool():
    client = FakeClient()
    await Todo().run(ctx=context(client), action='list', done=True)
    await Todo().run(ctx=context(client), action='list', done=False)
    assert client.listed == [True, False]


async def test_list_refuses_a_done_filter_that_is_not_a_bool():
    client = FakeClient()
    result = await Todo().run(ctx=context(client), action='list', done='true')
    assert result == 'Error: list needs done to be true or false'
    assert client.listed == []


async def test_create_posts_only_the_fields_it_was_given():
    client = FakeClient()
    result = await Todo().run(ctx=context(client), action='create', title='寫 issue', sort_order=2)
    assert client.created == [{'title': '寫 issue', 'sort_order': 2}]
    assert json.loads(result)['title'] == '寫 issue'


async def test_create_needs_a_title():
    client = FakeClient()
    result = await Todo().run(ctx=context(client), action='create', description='冇題目')
    assert result == 'Error: create needs a title'
    assert client.created == []


async def test_update_sends_only_the_fields_it_was_given():
    client = FakeClient()
    result = await Todo().run(ctx=context(client), action='update', id=TODO['id'], done=True)
    assert client.updated == [(TODO['id'], {'done': True})]
    assert json.loads(result)['id'] == TODO['id']


async def test_update_with_an_explicit_null_due_at_clears_it():
    client = FakeClient()
    await Todo().run(ctx=context(client), action='update', id=TODO['id'], due_at=None)
    assert client.updated == [(TODO['id'], {'due_at': None})]


async def test_update_needs_a_field_to_change():
    client = FakeClient()
    result = await Todo().run(ctx=context(client), action='update', id=TODO['id'])
    assert result == 'Error: update needs at least one field to change'
    assert client.updated == []


async def test_update_needs_an_id():
    result = await Todo().run(ctx=context(FakeClient()), action='update', title='x')
    assert result == 'Error: update needs an id'


async def test_delete_reports_the_row_it_removed():
    client = FakeClient()
    result = await Todo().run(ctx=context(client), action='delete', id=TODO['id'])
    assert client.deleted == [TODO['id']]
    assert json.loads(result) == {'deleted': TODO['id']}


async def test_an_unknown_action_is_refused_before_the_client_is_touched():
    result = await Todo().run(ctx=context(FakeClient()), action='tick', id=TODO['id'])
    assert result == 'Error: action must be one of create, list, update, delete'


async def test_a_missing_client_answers_with_an_error_instead_of_raising():
    result = await Todo().run(ctx=ToolContext(), action='list')
    assert result == 'Error: data cloud not configured'


def test_the_schema_is_available_without_a_client():
    schema = Todo().get_openai_schema()
    assert schema['function']['name'] == 'todo'
    assert schema['function']['parameters']['properties']['action']['enum'] == ['create', 'list', 'update', 'delete']
    assert schema['function']['parameters']['required'] == ['action']
