import json
from typing import Any

from rqark_core.core import AgentCore
from rqark_core.tools.subagent import SubAgent
from rqark_core.types.chat import AssistantMessage
from rqark_core.types.provider import Provider
from rqark_core.types.tool import ToolContext

from rqark_app.tools import Task
from rqark_app.tools.context import CLIENT_KEY
from rqark_app.tools.task import TASK_ORIGIN_KEY

TASK = {
    'id': 'task-1',
    'name': 'Morning brief',
    'prompt': 'Summarise my inbox.',
    'agent_name': 'Angel Holiday',
    'provider_name': 'openai',
    'timezone': 'Asia/Hong_Kong',
    'enabled': True,
    'schedule_kind': 'cron',
    'run_at': None,
    'every_seconds': None,
    'cron_expr': '0 9 * * *',
    'next_run_at': '2026-10-19T01:00:00Z',
}


class FakeClient:
    def __init__(self) -> None:
        self.tasks: list[dict] = [TASK]
        self.created: list[dict] = []
        self.updated: list[tuple[str, dict]] = []
        self.deleted: list[str] = []
        self.ran: list[str] = []

    async def list_tasks(self) -> list[dict]:
        return self.tasks

    async def create_task(self, payload: dict) -> dict:
        self.created.append(payload)
        return {'id': 'task-1', **payload}

    async def update_task(self, uuid: str, payload: dict) -> dict:
        self.updated.append((uuid, payload))
        return {**TASK, 'id': uuid, **payload}

    async def delete_task(self, uuid: str) -> None:
        self.deleted.append(uuid)

    async def run_task(self, uuid: str) -> dict:
        self.ran.append(uuid)
        return {**TASK, 'id': uuid}


def context(client: FakeClient | None = None, **extra: Any) -> ToolContext:
    extras: dict[str, Any] = dict(extra)
    if client is not None:
        extras[CLIENT_KEY] = client
    return ToolContext(extras=extras)


async def test_create_posts_the_task_and_prunes_the_other_schedule_fields():
    client = FakeClient()
    result = await Task().run(
        ctx=context(client),
        action='create',
        name='Morning brief',
        prompt='Summarise my inbox.',
        agent_name='Angel Holiday',
        provider_name='openai',
        timezone='Asia/Hong_Kong',
        schedule_kind='cron',
        cron_expr='0 9 * * *',
        run_at='2026-10-19T01:00:00Z',
    )
    assert client.created[0] == {'name': 'Morning brief', 'prompt': 'Summarise my inbox.', 'agent_name': 'Angel Holiday', 'provider_name': 'openai', 'timezone': 'Asia/Hong_Kong', 'schedule_kind': 'cron', 'cron_expr': '0 9 * * *'}
    assert json.loads(result)['id'] == 'task-1'
    assert json.loads(result)['schedule_kind'] == 'cron'


async def test_create_refuses_a_schedule_without_its_own_field():
    client = FakeClient()
    result = await Task().run(ctx=context(client), action='create', name='x', prompt='p', agent_name='a', provider_name='b', schedule_kind='every')
    assert result == "Error: schedule_kind 'every' needs every_seconds"
    assert client.created == []


async def test_create_names_every_missing_field():
    result = await Task().run(ctx=context(FakeClient()), action='create', name='x')
    assert result == 'Error: create needs prompt, agent_name, provider_name, schedule_kind'


async def test_list_returns_the_tasks_with_the_stable_keys():
    client = FakeClient()
    result = await Task().run(ctx=context(client), action='list')
    rows = json.loads(result)
    assert rows == [TASK]
    assert client.created == []


async def test_update_sends_only_the_fields_it_was_given():
    client = FakeClient()
    result = await Task().run(ctx=context(client), action='update', uuid='task-1', prompt='Summarise only the unread ones.', enabled=False)
    assert client.updated == [('task-1', {'prompt': 'Summarise only the unread ones.', 'enabled': False})]
    assert json.loads(result)['id'] == 'task-1'


async def test_update_replaces_the_whole_schedule():
    client = FakeClient()
    await Task().run(ctx=context(client), action='update', uuid='task-1', schedule_kind='every', every_seconds=3600, cron_expr='0 9 * * *')
    assert client.updated[0][1] == {'schedule_kind': 'every', 'every_seconds': 3600}


async def test_update_needs_a_field_to_change():
    client = FakeClient()
    result = await Task().run(ctx=context(client), action='update', uuid='task-1')
    assert result == 'Error: update needs at least one field to change'
    assert client.updated == []


async def test_update_needs_a_uuid():
    result = await Task().run(ctx=context(FakeClient()), action='update', prompt='p')
    assert result == 'Error: update needs a uuid'


async def test_delete_reports_the_row_it_removed():
    client = FakeClient()
    result = await Task().run(ctx=context(client), action='delete', uuid='task-1')
    assert client.deleted == ['task-1']
    assert json.loads(result) == {'deleted': 'task-1'}


async def test_run_now_answers_with_the_task():
    client = FakeClient()
    result = await Task().run(ctx=context(client), action='run_now', uuid='task-1')
    assert client.ran == ['task-1']
    assert json.loads(result)['id'] == 'task-1'


async def test_an_unknown_action_is_refused_before_the_client_is_touched():
    client = FakeClient()
    result = await Task().run(ctx=context(client), action='pause')
    assert result == 'Error: action must be one of create, list, update, delete, run_now'


async def test_a_missing_client_answers_with_an_error_instead_of_raising():
    result = await Task().run(ctx=ToolContext(), action='list')
    assert result == 'Error: data cloud not configured'


async def test_a_task_run_may_only_list():
    client = FakeClient()
    for action, extra in [
        ('create', {'name': 'x', 'prompt': 'p', 'agent_name': 'a', 'provider_name': 'b', 'schedule_kind': 'cron', 'cron_expr': '0 9 * * *'}),
        ('update', {'uuid': 'task-1', 'prompt': 'p'}),
        ('delete', {'uuid': 'task-1'}),
        ('run_now', {'uuid': 'task-1'}),
    ]:
        result = await Task().run(ctx=context(client, **{TASK_ORIGIN_KEY: True}), action=action, **extra)
        assert result == 'Error: a task run may only list tasks'
    assert (client.created, client.updated, client.deleted, client.ran) == ([], [], [], [])

    result = await Task().run(ctx=context(client, **{TASK_ORIGIN_KEY: True}), action='list')
    assert json.loads(result) == [TASK]


async def test_a_subagent_child_core_carries_the_task_origin_refusal(monkeypatch: Any):
    client = FakeClient()
    extras = {CLIENT_KEY: client, TASK_ORIGIN_KEY: True}
    seen: list[Any] = []

    class ChildCore(AgentCore):
        def __init__(self, **kwargs: Any) -> None:
            seen.append(kwargs.get('extras'))
            super().__init__(**kwargs)

        async def chat(self, provider: Any, messages: Any, prompts: Any = (), tools: Any = ()) -> tuple[list[AssistantMessage], None]:
            result = await Task().run(ctx=ToolContext(extras=seen[-1]), action='create', name='x', prompt='p', agent_name='a', provider_name='b', schedule_kind='cron', cron_expr='0 9 * * *')
            return [AssistantMessage(result)], None

    monkeypatch.setattr('rqark_core.tools.subagent.AgentCore', ChildCore)

    tool = SubAgent([], [Task()])
    provider = Provider('model', 'http://test', 0, 'key')
    result = await tool.run(ctx=ToolContext(core=AgentCore(), provider=provider, extras=extras), prompt='go')

    assert result == 'Error: a task run may only list tasks'
    assert seen == [extras]
    assert client.created == []


def test_the_schema_is_available_without_a_client():
    schema = Task().get_openai_schema()
    assert schema['function']['name'] == 'task'
    assert schema['function']['parameters']['properties']['action']['enum'] == ['create', 'list', 'update', 'delete', 'run_now']
    assert schema['function']['parameters']['required'] == ['action']
