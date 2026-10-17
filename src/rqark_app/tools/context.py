from datetime import UTC, datetime
from typing import Any

from rqark_core.types.tool import ToolContext

from rqark_app.cloud.client import RQArkDataCloudClient

CLIENT_KEY = 'data_cloud'
AGENT_KEY = 'agent_id'
SOURCE_KEY = 'source'


def context_parts(ctx: ToolContext | None) -> tuple[RQArkDataCloudClient, str, str]:
    extras = ctx.extras if ctx is not None else {}
    client = extras.get(CLIENT_KEY)
    agent_id = extras.get(AGENT_KEY)
    source = extras.get(SOURCE_KEY)
    if client is None:
        raise RuntimeError(f'memory needs a data cloud client in ToolContext.extras[{CLIENT_KEY!r}]')
    if not agent_id:
        raise RuntimeError(f'memory needs an agent id in ToolContext.extras[{AGENT_KEY!r}]')
    if not source:
        raise RuntimeError(f'memory needs a source in ToolContext.extras[{SOURCE_KEY!r}]')
    return client, str(agent_id), str(source)


def iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    return str(value)
