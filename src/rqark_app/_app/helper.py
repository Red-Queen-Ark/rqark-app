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

def _turn_starts(messages: list[Message]) -> list[int]:
    starts = [i for i, m in enumerate(messages) if isinstance(m, UserMessage)]
    if not starts or starts[0] != 0:
        starts = [0, *starts]
    return starts

def _trim_middle(messages: list[Message], head: int, tail: int) -> list[Message] | None:
    starts = _turn_starts(messages)
    if head + tail >= len(starts):
        return None
    end = starts[head]
    begin = starts[-tail] if tail else len(messages)
    if end >= begin:
        return None
    return messages[:end] + messages[begin:]

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
        messages = filtered
        while True:
            new_messages, error = await core.chat(provider, messages, [CompactContext()], [])
            if error is None and new_messages:
                return SummaryMessage(new_messages[-1].content)
            shrunk: list[Message] | None = None
            for head, tail in ((2, 2), (1, 1), (0, 1)):
                candidate = _trim_middle(filtered, head, tail)
                if candidate is not None and len(candidate) < len(messages):
                    shrunk = candidate
                    break
            if shrunk is None:
                return None
            messages = shrunk
