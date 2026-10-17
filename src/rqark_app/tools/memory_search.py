import json
from typing import Any

from rqark_core.types.tool import BaseTool, ToolContext

from rqark_app.tools.context import context_parts, iso

_prompt = """
## Memory search
memory_search reads the memory log of this agent. Search by keywords first — they are the index.
Pass `at` to ask what was true before a moment in time, not to fetch a single row.
"""


class MemorySearch(BaseTool):
    @property
    def name(self) -> str:
        return 'memory_search'

    def tool_prompt(self, ctx: ToolContext | None = None) -> str:
        return _prompt

    def get_openai_schema(self) -> dict[str, Any]:
        return {
            'type': 'function',
            'function': {
                'name': self.name,
                'description': 'Search your memory log for this user. Returns at most 20 rows, ranked by keyword matches, then relevance decayed with age, then recency. Pinned rows are not ranked first here.',
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'query': {'type': 'string', 'description': 'Substring to look for in the content or a keyword.'},
                        'keywords': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Keywords to match; each hit raises the rank.'},
                        'at': {'type': 'string', 'description': 'ISO 8601 upper bound on occurred_at, for what was true before that moment.'},
                    },
                },
            },
        }

    async def run(self, ctx: ToolContext | None = None, **kwargs: Any) -> str:
        client, agent_id, _ = context_parts(ctx)
        keywords = kwargs.get('keywords')
        rows = await client.search_memory(agent_id, query=kwargs.get('query') or None, keywords=[str(keyword) for keyword in keywords] if keywords else None, at=iso(kwargs.get('at')))
        return json.dumps([{'id': row.get('id'), 'content': row.get('content'), 'keywords': row.get('keywords'), 'occurred_at': row.get('occurred_at'), 'pinned': row.get('pinned')} for row in rows], ensure_ascii=False)
