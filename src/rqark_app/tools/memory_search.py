import json
from typing import Any

from rqark_core.types.tool import BaseTool, ToolContext

from rqark_app.tools.context import context_parts, iso

_prompt = """
## Memory search
memory_search reads the memory log of this agent. Search by keywords first — they are the index.
Pass from and to to read one stretch of the log: both are inclusive, either may be sent alone, and ISO 8601 dates are enough (2026-09-01). A window with neither bound reads the whole log.
A row is recorded once, at the moment it happened, so a question about a period means a window, not a single date.
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
                'description': 'Search your memory log for this user. Returns at most 20 rows of both kinds ("fact" from memory_save, "event" from the automatic per-turn log), ranked by keyword matches, then relevance decayed with age, then recency. Pinned rows are not ranked first here. from and to bound the row\'s occurred_at, both inclusive, so "what did we decide last month" is from 2026-09-01 to 2026-09-30.',
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'query': {'type': 'string', 'description': 'Substring to look for in the content or a keyword.'},
                        'keywords': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Keywords to match; each hit raises the rank.'},
                        'from': {'type': 'string', 'description': 'ISO 8601 lower bound on occurred_at, inclusive. Omit to read from the beginning.'},
                        'to': {'type': 'string', 'description': 'ISO 8601 upper bound on occurred_at, inclusive. Omit to read up to now.'},
                    },
                },
            },
        }

    async def run(self, ctx: ToolContext | None = None, **kwargs: Any) -> str:
        client, agent_id, _ = context_parts(ctx)
        keywords = kwargs.get('keywords')
        rows = await client.search_memory(agent_id, query=kwargs.get('query') or None, keywords=[str(keyword) for keyword in keywords] if keywords else None, start=iso(kwargs.get('from')), end=iso(kwargs.get('to')))
        return json.dumps(
            [{'id': row.get('id'), 'content': row.get('content'), 'keywords': row.get('keywords'), 'kind': row.get('kind'), 'occurred_at': row.get('occurred_at'), 'pinned': row.get('pinned')} for row in rows], ensure_ascii=False
        )
