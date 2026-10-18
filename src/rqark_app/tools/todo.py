import json
from typing import Any

from rqark_core.types.tool import BaseTool, ToolContext

from rqark_app.tools.context import CLIENT_KEY

_NO_CLOUD = 'Error: data cloud not configured'
_ACTIONS = ('create', 'list', 'update', 'delete')
_FIELDS = ('title', 'description', 'done', 'due_at', 'sort_order')
_ROW_KEYS = ('id', 'title', 'description', 'done', 'done_at', 'due_at', 'sort_order')

_prompt = """
## Todos
`todo` reads and writes the todo list of this user in the data cloud, one `action` per call: `create`, `list`, `update`, `delete`.
The todo list belongs to the user and is what the user wants to get done; it is not a plan for the current run.
`list` takes an optional `done` filter. `create` needs a `title`; `description`, `due_at` and `sort_order` are optional.
`update` sends only the fields to change, and `due_at: null` clears the due date. `done` is a boolean: the server records when it was ticked.
"""


def _row(todo: dict) -> dict:
    return {key: todo.get(key) for key in _ROW_KEYS}


def _error(message: str) -> str:
    return f'Error: {message}'


class Todo(BaseTool):
    @property
    def name(self) -> str:
        return 'todo'

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
                'description': 'Create, list, update and delete the todo items of this user in the data cloud. Each call takes one action and answers with JSON.',
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'action': {'type': 'string', 'enum': list(_ACTIONS), 'description': 'What to do with the todo list.'},
                        'id': {'type': 'string', 'description': 'The todo id, for update and delete.'},
                        'done': {'type': 'boolean', 'description': 'Whether the todo is finished. On list it filters the list; on update it ticks or unticks.'},
                        'title': {'type': 'string', 'description': 'What the todo is.'},
                        'description': {'type': 'string', 'description': 'Longer notes for the todo.'},
                        'due_at': {'type': ['string', 'null'], 'description': 'ISO 8601 instant the todo is due, or null to clear it.'},
                        'sort_order': {'type': 'integer', 'description': 'Position in the list; lower comes first.'},
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
        client = extras.get(CLIENT_KEY)
        if client is None:
            return _NO_CLOUD
        if action == 'list':
            done = kwargs.get('done')
            if done is not None and not isinstance(done, bool):
                return _error('list needs done to be true or false')
            return json.dumps([_row(todo) for todo in await client.list_todos(done)], ensure_ascii=False)
        if action == 'create':
            return await self._create(client, kwargs)
        uuid = kwargs.get('id')
        if not isinstance(uuid, str) or not uuid.strip():
            return _error(f'{action} needs an id')
        if action == 'update':
            return await self._update(client, uuid, kwargs)
        await client.delete_todo(uuid)
        return json.dumps({'deleted': uuid}, ensure_ascii=False)

    async def _create(self, client: Any, kwargs: dict[str, Any]) -> str:
        payload = self._payload(kwargs)
        title = payload.get('title')
        if not isinstance(title, str) or not title.strip():
            return _error('create needs a title')
        todo = await client.create_todo(payload)
        return json.dumps(_row(todo), ensure_ascii=False)

    async def _update(self, client: Any, uuid: str, kwargs: dict[str, Any]) -> str:
        payload = self._payload(kwargs)
        if 'due_at' in kwargs:
            payload['due_at'] = kwargs['due_at']
        if not payload:
            return _error('update needs at least one field to change')
        todo = await client.update_todo(uuid, payload)
        return json.dumps(_row(todo), ensure_ascii=False)

    @staticmethod
    def _payload(kwargs: dict[str, Any]) -> dict[str, Any]:
        payload = {field: kwargs[field] for field in _FIELDS if kwargs.get(field) is not None}
        if 'sort_order' in payload:
            payload['sort_order'] = int(payload['sort_order'])
        return payload
