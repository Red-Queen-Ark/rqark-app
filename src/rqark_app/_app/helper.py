import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import replace

from openai import APIError
from rqark_core.core import AgentCore
from rqark_core.types.chat import AssistantMessage, Message, UserMessage
from rqark_core.types.event import AgentPayload
from rqark_core.types.provider import Provider

from rqark_app.prompts.compact import CompactContext
from rqark_app.prompts.title import GentTilte
from rqark_app.provider.manager import ProviderManager
from rqark_app.session.manager import SessionManager
from rqark_app.types.event import ProviderSwitch
from rqark_app.types.session import Session, SummaryMessage

_CONTEXT_OVERFLOW_RE = re.compile(r'maximum context length', re.IGNORECASE)

class ChatHelper:
    def __init__(self, provider_mgr: ProviderManager, session_mgr: SessionManager, emit: Callable[..., Awaitable[None]]):
        self.provider_mgr = provider_mgr
        self.session_mgr = session_mgr
        self._emit = emit

    async def report_failure(self, core: AgentCore, provider: Provider):
        self.provider_mgr.report_failure()
        if self.provider_mgr.provider is not provider:
            await self._emit('provider_switched', AgentPayload(core.agent_id, core.path, ProviderSwitch(old=provider, new=self.provider_mgr.provider)))
        await asyncio.sleep(1)

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

    def is_context_overflow(self, error: Exception) -> bool:
        if not isinstance(error, APIError):
            return False
        body = error.body
        if not isinstance(body, dict):
            return False
        err = body.get('error')
        if not isinstance(err, dict):
            return False
        message = err.get('message')
        return isinstance(message, str) and _CONTEXT_OVERFLOW_RE.search(message) is not None

    async def get_summary(self, session_id: str) -> SummaryMessage | None:
        session = await self.session_mgr.get(session_id)
        if session is None:
            return None
        filtered: list[Message] = []
        for m in session.get_last_chunk():
            if isinstance(m, SummaryMessage):
                filtered.append(m.to_message())
            elif isinstance(m, AssistantMessage):
                filtered.append(replace(m, reasoning_content=None))
            else:
                filtered.append(m)
        if not filtered:
            return None
        core = AgentCore(f'Compact:{session_id}')
        provider = self.provider_mgr.provider
        new_messages, error = await core.chat(provider, filtered, [CompactContext()], [])
        if error is not None or not new_messages:
            return None
        content = new_messages[-1].content
        summary = SummaryMessage(content)
        return summary
