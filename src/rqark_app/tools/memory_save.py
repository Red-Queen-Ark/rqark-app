import json
from datetime import UTC, datetime
from typing import Any

from rqark_core.types.tool import BaseTool, ToolContext

from rqark_app.tools.context import context_parts, iso

_prompt = """
## Memory
memory_save appends one fact worth remembering to the memory log of this agent.
Write short, self-contained facts: a preference, a decision, a deadline, who someone is.
Never rewrite or retract a row — the log is append-only and only the user deletes. If an earlier row is wrong, save a new row that supersedes it and say so in the content.
Save only what stays useful next session. Skip anything the transcript already carries.
Pinning is the user's call, not yours: write the fact and let them decide what stays at the top.
"""


class MemorySave(BaseTool):
    @property
    def name(self) -> str:
        return 'memory_save'

    @property
    def display_key(self) -> str:
        return 'content'

    def tool_prompt(self, ctx: ToolContext | None = None) -> str:
        return _prompt

    def get_openai_schema(self) -> dict[str, Any]:
        return {
            'type': 'function',
            'function': {
                'name': self.name,
                'description': "Append one fact to your memory log for this user. The log is append-only: a saved row cannot be edited or deleted by you, only by the user. content is at most 200 characters and keywords at most 8. Pinning is the user's call, so it is not a parameter here.",
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'content': {'type': 'string', 'description': 'The fact to remember, at most 200 characters, self-contained.'},
                        'keywords': {'type': 'array', 'items': {'type': 'string'}, 'description': 'At most 8 search keywords.'},
                        'occurred_at': {'type': 'string', 'description': 'ISO 8601 time the fact happened, when it is not now.'},
                        'source_message': {'type': 'object', 'description': 'The original message this fact was taken from.'},
                    },
                    'required': ['content'],
                },
            },
        }

    async def run(self, ctx: ToolContext | None = None, **kwargs: Any) -> str:
        client, agent_id, source = context_parts(ctx)
        content = kwargs.get('content')
        if not isinstance(content, str) or not content.strip():
            raise TypeError('content is required')
        payload: dict[str, Any] = {'agent_id': agent_id, 'content': content, 'source': source}
        keywords = kwargs.get('keywords')
        if keywords:
            payload['keywords'] = [str(keyword) for keyword in keywords]
        payload['occurred_at'] = iso(kwargs.get('occurred_at')) or datetime.now(UTC).isoformat()
        source_message = kwargs.get('source_message')
        if source_message is not None:
            payload['source_message'] = source_message
        saved = await client.create_memory(payload)
        return json.dumps({'id': saved.get('id'), 'content': saved.get('content'), 'occurred_at': saved.get('occurred_at')}, ensure_ascii=False)
