from datetime import UTC, datetime
from typing import Any

from rqark_core.types.prompt import BasePrompt, PromptContext

from rqark_app.cloud.client import DataCloudError, RQArkDataCloudClient
from rqark_app.tools.context import AGENT_KEY, CLIENT_KEY

_head = """# Memory
What you recorded for this user in earlier sessions. Treat them as fact, but a row only describes the moment it was recorded: when a newer row contradicts an older one, the newer one wins.
Never read this list back to the user. Use it quietly to answer and to act."""

PROMPT_KEY = '_memory_prompt'


async def load_prompt_memory(client: RQArkDataCloudClient, agent_id: str, extras: dict[str, Any]) -> dict:
    """The current state and the fact rows for one turn, fetched at most once.

    Returns an empty dict when the data cloud cannot answer: the prompt is an
    enrichment, never a reason for the turn to fail.
    """
    cached = extras.get(PROMPT_KEY)
    if isinstance(cached, dict):
        return cached
    try:
        payload = await client.prompt_memory(agent_id)
    except DataCloudError:
        return {}
    if not isinstance(payload, dict):
        return {}
    extras[PROMPT_KEY] = payload
    return payload


class MemoryPrompt(BasePrompt):
    priority = 25

    async def get_messages(self, ctx: PromptContext | None = None) -> str | None:
        extras = ctx.extras if ctx is not None else {}
        client = extras.get(CLIENT_KEY)
        agent_id = extras.get(AGENT_KEY)
        if not isinstance(client, RQArkDataCloudClient) or not agent_id:
            return None
        payload = await load_prompt_memory(client, str(agent_id), extras)
        rows = payload.get('memories')
        if not isinstance(rows, list):
            return None
        entries = [self._entry(row) for row in rows if isinstance(row, dict) and row.get('content')]
        if not entries:
            return None
        return '\n'.join([_head, '', *entries])

    @staticmethod
    def _entry(row: dict) -> str:
        occurred_at = row.get('occurred_at') or ''
        try:
            occurred_at = datetime.fromisoformat(str(occurred_at)).astimezone(UTC).strftime('%Y-%m-%d %H:%M UTC')
        except ValueError:
            occurred_at = str(occurred_at)
        pinned = ' pinned' if row.get('pinned') else ''
        return f'- [{occurred_at}{pinned}] {row["content"]}'
