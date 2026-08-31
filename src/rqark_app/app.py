import asyncio
from collections.abc import Sequence

from openai import APIError
from rqark_core.core import AgentCore
from rqark_core.types.chat import Message, UserMessage
from rqark_core.types.event import AgentPayload
from rqark_core.types.provider import Provider
from rqark_core.types.tool import PlanItem

from rqark_app._app.event import AgentAppEventEmitter
from rqark_app.provider.manager import ProviderManager
from rqark_app.session.manager import SessionManager
from rqark_app.session.storage import SessionStorage
from rqark_app.types.agent import BaseAgent
from rqark_app.types.event import ProviderSwitch
from rqark_app.types.session import Session
from rqark_app.prompts.title import GentTilte
from rqark_app.prompts.compact import CompactContext

class AgentApp(AgentAppEventEmitter):
    def __init__(self, providers: list[Provider], storage: SessionStorage | None = None):
        super().__init__()
        self.provider_mgr = ProviderManager(providers)
        self.session_mgr = SessionManager(storage)
        
    def _connect_event(self, core: AgentCore):
        core.on_chunk()(self.handle_chunk_event)
        core.on_message()(self.handle_message_event)
        core.on_plan()(self.handle_plan)
        core.on_plan()(self.handle_save_plan)

    async def handle_save_plan(self, ev: AgentPayload[list[PlanItem]]):
        session = await self.session_mgr.set_plan(ev.agent_id, ev.payload)
        if session is not None:
            await self.session_mgr.save(session.uuid)

    async def gen_title(self, session_id: str, content: str) -> Session | None:
        session = await self.session_mgr.get(session_id)
        if session is None:
            return None
        core = AgentCore('GenTitle')
        provider = self.provider_mgr.provider
        for _ in range(3):
            new_messages, error = await core.chat(provider, [ UserMessage(content) ], [ GentTilte() ], [])
            if error is None:
                session.title = new_messages[-1].content
                await self.session_mgr.save(session.uuid)
            else:
                await self.report_failure(core, provider)
        return session
    
    async def compact_context(self, session_id: str):
        ...
    
    async def chat(self, content: str, agent: BaseAgent, session_id: str | None = None, path: tuple[str, ...] = ()) -> Session:
        session = await self.session_mgr.get_or_create(session_id) if session_id else await self.session_mgr.create()
        core = AgentCore(f'{agent.name}:{session.uuid}', path=path)
        user_msg = UserMessage(content)
        await self._emit('message', AgentPayload(core.agent_id, core.path, user_msg))
        self._connect_event(core)
        history = [*session.history, user_msg]
        return await self._loop(session, core, agent, history)

    async def _loop(self, session: Session, core: AgentCore, agent: BaseAgent, history: list[Message]) -> Session:
        while True:
            provider = self.provider_mgr.provider
            new_messages, error = await core.chat(provider, history, agent.prompts, agent.tools)
            history = list(new_messages)
            session.history = history
            await self.session_mgr.save(session.uuid)
            if error is None:
                return session
            if not isinstance(error, APIError):
                raise error

            await self.report_failure(core, provider)
    
    async def report_failure(self, core: AgentCore, provider: Provider):
        self.provider_mgr.report_failure()
        if self.provider_mgr.provider is not provider:
            await self._emit('provider_switched', AgentPayload(core.agent_id, core.path, ProviderSwitch(old=provider, new=self.provider_mgr.provider)))
        await asyncio.sleep(1)