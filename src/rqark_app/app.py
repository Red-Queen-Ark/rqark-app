from collections.abc import Sequence
from rqark_core.core import AgentCore, Chunk, ToolMessage
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
        
        last_chunk_type = Chunk('reasoning_content', '')
        @core.on_chunk()
        async def print_chunk(chunk: Chunk):
            nonlocal last_chunk_type
            if last_chunk_type.type != chunk.type:
                print()
            if chunk.type == 'reasoning_content':
                print(chunk.content, flush=True, end='')
            elif chunk.type == 'content':
                print(chunk.content, flush=True, end='')
            elif chunk.type == 'tool_calls' and isinstance(chunk.content, list):
                for call in chunk.content:
                    print(call.name, call.arguments)
            elif chunk.type == 'tool_result' and isinstance(chunk.content, ToolMessage):
                print(chunk.content.tool_name, chunk.content.content)
            elif chunk.type == 'error':
                print(f'[error] {chunk.content}')
            last_chunk_type = chunk
    
        provider = self.provider_mgr.provider
        agent = self.agent_mgr.agent
        messages = [ UserMessage(content) ]
        new_messages, error = await core.chat(provider, messages, agent.prompts, agent.tools)
        return new_messages
