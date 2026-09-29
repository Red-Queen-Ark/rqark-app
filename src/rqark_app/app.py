from openai import APIError
from rqark_core.core import AgentCore
from rqark_core.types.chat import Message, UserMessage
from rqark_core.types.event import AgentPayload
from rqark_core.types.provider import Provider
from rqark_core.types.tool import PlanItem

from rqark_app._app.event import AgentAppEventEmitter
from rqark_app._app.helper import ChatHelper
from rqark_app.provider.manager import ProviderManager
from rqark_app.session.manager import SessionManager
from rqark_app.session.storage import SessionStorage
from rqark_app.types.agent import BaseAgent
from rqark_app.types.session import Session


class AgentApp(AgentAppEventEmitter):
    def __init__(self, providers: list[Provider], storage: SessionStorage | None = None):
        super().__init__()
        self.provider_mgr = ProviderManager(providers)
        self.session_mgr = SessionManager(storage)
        self.chat_helper = ChatHelper(self.provider_mgr, self.session_mgr, self._emit)

    def _connect_event(self, core: AgentCore):
        core.on_chunk()(self.handle_chunk_event)
        core.on_message()(self.handle_message_event)
        core.on_plan()(self.handle_plan)
        core.on_plan()(self.handle_save_plan)

    async def handle_save_plan(self, ev: AgentPayload[list[PlanItem]]):
        session = await self.session_mgr.set_plan(ev.agent_id, ev.payload)
        if session is not None:
            await self.session_mgr.save(session.uuid)

    async def chat(self, content: str, agent: BaseAgent, session_id: str | None = None, path: tuple[str, ...] = (), images: list[str] | None = None) -> Session:
        session = await self.session_mgr.get_or_create(session_id) if session_id else await self.session_mgr.create()
        core = AgentCore(f'{agent.name}:{session.uuid}', path=path)
        user_msg = UserMessage(content, images=list(images) if images else [])
        await self._emit('message', AgentPayload(core.agent_id, core.path, user_msg))
        self._connect_event(core)
        history = [*session.get_last_chunk_for_chat(), user_msg]
        return await self._loop(session, core, agent, history)

    async def _loop(self, session: Session, core: AgentCore, agent: BaseAgent, history: list[Message]) -> Session:
        while True:
            provider = self.provider_mgr.provider
            # needs_compression
            if self.chat_helper.needs_compression(history, provider):
                persisted = session.get_last_chunk_for_chat()
                summary = await self.chat_helper.get_summary(persisted)
                if summary:
                    session.history += [summary]
                    await self.session_mgr.save(session.uuid)
                    in_flight = history[len(persisted) :] if len(history) > len(persisted) else []
                    history = [*session.get_last_chunk_for_chat(), *in_flight]
            #
            new_messages, error = await core.chat(provider, history, agent.prompts, agent.tools)
            history = list(new_messages)
            session.update_history_to_last_chunk(history)
            await self.session_mgr.save(session.uuid)
            if error is None:
                return session
            if not isinstance(error, APIError):
                raise error
            if self.chat_helper.is_context_overflow(error):
                summary = await self.chat_helper.get_summary(session.get_last_chunk_for_chat())
                if summary:
                    session.history += [summary]
                    await self.session_mgr.save(session.uuid)
                    history = session.get_last_chunk_for_chat()
            await self.chat_helper.report_failure(core, provider)
