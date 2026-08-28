from collections.abc import Sequence
from rqark_core.core import AgentCore
from rqark_core.types.provider import Provider
from rqark_app.provider.manager import ProviderManager
from rqark_app.types.agent import BaseAgent
from rqark_app.agent.manager import AgentManager
from rqark_core.types.chat import Message, UserMessage

class AgentApp:
    def __init__(self, providers: list[Provider], agents: Sequence[BaseAgent]):
        self.provider_mgr = ProviderManager(providers)
        self.agent_mgr = AgentManager(agents)
        # self.session_mgr = 
        # self.event_mgr = 

    async def chat(self, content: str) -> Sequence[Message]:
        core = AgentCore()
        provider = self.provider_mgr.provider
        agent = self.agent_mgr.agent
        messages = [ UserMessage(content) ]
        new_messages, error = await core.chat(provider, messages, agent.prompts, agent.tools)
        print(error)
        return new_messages
