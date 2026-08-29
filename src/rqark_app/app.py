from collections.abc import Sequence

from rqark_core.core import AgentCore, ToolMessage
from rqark_core.types.chat import Message, UserMessage, Chunk
from rqark_core.types.provider import Provider

from rqark_app._app.event import AgentAppEventEmitter
from rqark_app.agent.manager import AgentManager
from rqark_app.provider.manager import ProviderManager
from rqark_app.types.agent import BaseAgent

class AgentApp(AgentAppEventEmitter):
    def __init__(self, providers: list[Provider], agents: Sequence[BaseAgent]):
        super().__init__()
        self.provider_mgr = ProviderManager(providers)
        self.agent_mgr = AgentManager(agents)
        # self.session_mgr =
        
    def _connect_event(self, core: AgentCore):
        core._listeners['chunk'].append(lambda chunk: self.handle_chunk_event(chunk))
        core._listeners['message'].append(lambda msg: self.hendle_message_event(msg))
        core._listeners['plan'].append(lambda plan_items: self.handle_plan(plan_items))
        
    async def chat(self, content: str) -> Sequence[Message]:
        core = AgentCore()
        self._connect_event(core)
        provider = self.provider_mgr.provider
        agent = self.agent_mgr.agent
        messages = [ UserMessage(content) ]
        new_messages, error = await core.chat(provider, messages, agent.prompts, agent.tools)
        return new_messages
