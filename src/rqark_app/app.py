import asyncio
from collections.abc import Sequence

from openai import APIError
from rqark_core.core import AgentCore
from rqark_core.types.chat import Message, UserMessage
from rqark_core.types.event import AgentPayload
from rqark_core.types.provider import Provider

from rqark_app._app.event import AgentAppEventEmitter
from rqark_app.provider.manager import ProviderManager
from rqark_app.types.agent import BaseAgent


class AgentApp(AgentAppEventEmitter):
    def __init__(self, providers: list[Provider]):
        super().__init__()
        self.provider_mgr = ProviderManager(providers)

    def _connect_event(self, core: AgentCore):
        core.on_chunk()(self.handle_chunk_event)
        core.on_message()(self.handle_message_event)
        core.on_plan()(self.handle_plan)

    async def chat(self, content: str, agent: BaseAgent) -> Sequence[Message]:
        core = AgentCore(agent.name)
        self._connect_event(core)
        user_msg = UserMessage(content)
        await self._emit('message', AgentPayload(core.agent_id, core.path, user_msg))
        while True:
            provider = self.provider_mgr.provider
            new_messages, error = await core.chat(provider, [user_msg], agent.prompts, agent.tools)
            if error is None:
                return new_messages
            if not isinstance(error, APIError):
                raise error
            self.provider_mgr.report_failure()
            await asyncio.sleep(1)

