from rqark_core.types.prompt import BasePrompt, PromptContext

from rqark_app.cloud.client import RQArkDataCloudClient
from rqark_app.prompts.memory import load_prompt_memory
from rqark_app.tools.context import AGENT_KEY, CLIENT_KEY

_head = """# Current State

> 上一個 turn 自動更新。呢個係現況，唔係歷史；同下面 Memory 衝突時以呢度為準。"""


class StatePrompt(BasePrompt):
    """The current situation board, rendered above the memory log.

    Priority 20 puts it after the subagent prompt (20) and before Memory (25):
    with a provider that combines the system prompts into one message, the order
    is the priority order, and the state is the first thing the agent should
    read.
    """

    priority = 20

    async def get_messages(self, ctx: PromptContext | None = None) -> str | None:
        extras = ctx.extras if ctx is not None else {}
        client = extras.get(CLIENT_KEY)
        agent_id = extras.get(AGENT_KEY)
        if not isinstance(client, RQArkDataCloudClient) or not agent_id:
            return None
        payload = await load_prompt_memory(client, str(agent_id), extras)
        state = payload.get('state')
        if not isinstance(state, dict):
            return None
        content = state.get('content')
        if not isinstance(content, str) or not content.strip():
            return None
        return f'{_head}\n\n{content.strip()}'
