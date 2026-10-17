import json
from typing import Any

from rqark_core.types.tool import BaseTool, ToolContext

from rqark_app.tools.context import CLIENT_KEY

TASK_ORIGIN_KEY = 'task_origin'
_NO_CLOUD = 'Error: data cloud not configured'
_ORIGIN_DENIED = 'Error: a task run may only list tasks'
_ACTIONS = ('create', 'list', 'update', 'delete', 'run_now')
_SCHEDULES = {'at': 'run_at', 'every': 'every_seconds', 'cron': 'cron_expr'}
_FIELDS = ('name', 'prompt', 'agent_name', 'provider_name', 'timezone', 'enabled', 'schedule_kind', 'run_at', 'every_seconds', 'cron_expr')
_ROW_KEYS = ('id', 'name', 'prompt', 'agent_name', 'provider_name', 'timezone', 'enabled', 'schedule_kind', 'run_at', 'every_seconds', 'cron_expr', 'next_run_at')

_prompt = """
## Tasks
`task` manages the scheduled tasks of this user in the data cloud, one `action` per call: `create`, `list`, `update`, `delete`, `run_now`.
A task runs `prompt` on `agent_name` with `provider_name`. `schedule_kind` picks the one schedule field: `run_at` for `at`, `every_seconds` (at least 60) for `every`, `cron_expr` (five fields) for `cron`, evaluated in `timezone`.
`update` sends only the fields to change; a new `schedule_kind` replaces the whole schedule.
`run_now` asks for one run at the next tick and leaves the schedule untouched.
A task that runs cannot create, change, delete or run tasks: inside a task run only `list` answers.
"""


def _row(task: dict) -> dict:
    return {key: task.get(key) for key in _ROW_KEYS}


def _error(message: str) -> str:
    return f'Error: {message}'


class Task(BaseTool):
    @property
    def name(self) -> str:
        return 'task'

    @property
    def display_key(self) -> str:
        return 'action'

    def tool_prompt(self, ctx: ToolContext | None = None) -> str:
        return _prompt

    def get_openai_schema(self) -> dict[str, Any]:
        return {
            'type': 'function',
            'function': {
                'name': self.name,
                'description': 'Create, list, update, delete and run the scheduled tasks of this user in the data cloud. Each call takes one action and answers with JSON.',
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'action': {'type': 'string', 'enum': list(_ACTIONS), 'description': 'What to do with the task log.'},
                        'uuid': {'type': 'string', 'description': 'The task id, for update, delete and run_now.'},
                        'name': {'type': 'string', 'description': 'Task name, unique per user.'},
                        'prompt': {'type': 'string', 'description': 'The prompt the task runs.'},
                        'agent_name': {'type': 'string', 'description': 'Name of the agent that runs the task.'},
                        'provider_name': {'type': 'string', 'description': 'Name, or model name, of the provider that runs the task.'},
                        'timezone': {'type': 'string', 'description': 'IANA timezone the schedule is evaluated in.'},
                        'enabled': {'type': 'boolean', 'description': 'Whether the schedule fires.'},
                        'schedule_kind': {'type': 'string', 'enum': list(_SCHEDULES), 'description': 'Which schedule field is set.'},
                        'run_at': {'type': 'string', 'description': 'ISO 8601 instant, for schedule_kind at.'},
                        'every_seconds': {'type': 'integer', 'minimum': 60, 'description': 'Gap between runs, for schedule_kind every.'},
                        'cron_expr': {'type': 'string', 'description': 'Five-field cron expression, for schedule_kind cron.'},
                    },
                    'required': ['action'],
                },
            },
        }

    async def run(self, ctx: ToolContext | None = None, **kwargs: Any) -> str:
        extras = ctx.extras if ctx is not None else {}
        action = kwargs.get('action')
        if action not in _ACTIONS:
            return _error(f'action must be one of {", ".join(_ACTIONS)}')
        if extras.get(TASK_ORIGIN_KEY) is True and action != 'list':
            return _ORIGIN_DENIED
        client = extras.get(CLIENT_KEY)
        if client is None:
            return _NO_CLOUD
        if action == 'list':
            return json.dumps([_row(task) for task in await client.list_tasks()], ensure_ascii=False)
        if action == 'create':
            return await self._create(client, kwargs)
        uuid = kwargs.get('uuid')
        if not isinstance(uuid, str) or not uuid.strip():
            return _error(f'{action} needs a uuid')
        if action == 'update':
            return await self._update(client, uuid, kwargs)
        if action == 'delete':
            await client.delete_task(uuid)
            return json.dumps({'deleted': uuid}, ensure_ascii=False)
        return json.dumps(_row(await client.run_task(uuid)), ensure_ascii=False)

    async def _create(self, client: Any, kwargs: dict[str, Any]) -> str:
        payload = self._payload(kwargs)
        missing = [field for field in ('name', 'prompt', 'agent_name', 'provider_name', 'schedule_kind') if not payload.get(field)]
        if missing:
            return _error(f'create needs {", ".join(missing)}')
        problem = self._schedule_problem(payload)
        if problem:
            return problem
        self._prune_schedule(payload)
        task = await client.create_task(payload)
        return json.dumps(_row(task), ensure_ascii=False)

    async def _update(self, client: Any, uuid: str, kwargs: dict[str, Any]) -> str:
        payload = self._payload(kwargs)
        if not payload:
            return _error('update needs at least one field to change')
        if 'schedule_kind' in payload:
            if problem := self._schedule_problem(payload):
                return problem
            self._prune_schedule(payload)
        task = await client.update_task(uuid, payload)
        return json.dumps(_row(task), ensure_ascii=False)

    @staticmethod
    def _payload(kwargs: dict[str, Any]) -> dict[str, Any]:
        payload = {field: kwargs[field] for field in _FIELDS if kwargs.get(field) is not None}
        if 'every_seconds' in payload:
            payload['every_seconds'] = int(payload['every_seconds'])
        return payload

    @staticmethod
    def _prune_schedule(payload: dict[str, Any]) -> None:
        field = _SCHEDULES[payload['schedule_kind']]
        for kind_field in _SCHEDULES.values():
            if kind_field != field:
                payload.pop(kind_field, None)

    @staticmethod
    def _schedule_problem(payload: dict[str, Any]) -> str | None:
        kind = payload.get('schedule_kind')
        field = _SCHEDULES.get(kind)
        if field is None:
            return _error(f'schedule_kind must be one of {", ".join(_SCHEDULES)}')
        if payload.get(field) is None:
            return _error(f'schedule_kind {kind!r} needs {field}')
        return None
