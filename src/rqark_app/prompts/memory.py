from datetime import UTC, datetime

from rqark_core.types.prompt import BasePrompt, PromptContext

from rqark_app.cloud.client import DataCloudError, RQArkDataCloudClient
from rqark_app.tools.context import AGENT_KEY, CLIENT_KEY

_head = """# Memory
What you recorded for this user in earlier sessions. Treat them as fact, but a row only describes the moment it was recorded: when a newer row contradicts an older one, the newer one wins.
Never read this list back to the user. Use it quietly to answer and to act."""


class MemoryPrompt(BasePrompt):
    priority = 25

    async def get_messages(self, ctx: PromptContext | None = None) -> str | None:
        extras = ctx.extras if ctx is not None else {}
        client = extras.get(CLIENT_KEY)
        agent_id = extras.get(AGENT_KEY)
        if not isinstance(client, RQArkDataCloudClient) or not agent_id:
            return None
        try:
            rows = await client.prompt_memory(str(agent_id))
        except DataCloudError:
            return None
        entries = [self._entry(row) for row in rows if row.get('content')]
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
