import asyncio
import re
from collections.abc import Awaitable, Callable, Sequence
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
from rqark_app.types.session import HistoryMessage, Session, SummaryMessage

_COMPRESSION_RATIO = 0.9

_CONTEXT_OVERFLOW_PATTERNS = (
    re.compile(r'prompt is too long', re.IGNORECASE),
    re.compile(r'request_too_large', re.IGNORECASE),
    re.compile(r'input is too long', re.IGNORECASE),
    re.compile(r'exceeds the context window', re.IGNORECASE),
    re.compile(r'maximum context length', re.IGNORECASE),
    re.compile(r'input token count.*exceeds the maximum', re.IGNORECASE),
    re.compile(r'tokens in request more than max tokens allowed', re.IGNORECASE),
    re.compile(r'maximum prompt length is \d+', re.IGNORECASE),
    re.compile(r'reduce the length of the messages', re.IGNORECASE),
    re.compile(r'exceeds (?:the )?maximum allowed input length', re.IGNORECASE),
    re.compile(r"is longer than the model'?s context length", re.IGNORECASE),
    re.compile(r'exceeds the available context size', re.IGNORECASE),
    re.compile(r'greater than the context length', re.IGNORECASE),
    re.compile(r'context window exceeds limit', re.IGNORECASE),
    re.compile(r'exceeded model token limit', re.IGNORECASE),
    re.compile(r'exceeds the context limit', re.IGNORECASE),
    re.compile(r'context[_ ]length[_ ]exceeded', re.IGNORECASE),
    re.compile(r'request entity too large', re.IGNORECASE),
    re.compile(r'context length is only \d+ tokens', re.IGNORECASE),
    re.compile(r'input length.*exceeds.*context length', re.IGNORECASE),
    re.compile(r'prompt too long', re.IGNORECASE),
    re.compile(r'too large for model with \d+ maximum context length', re.IGNORECASE),
    re.compile(r'model_context_window_exceeded', re.IGNORECASE),
    re.compile(r'too many tokens', re.IGNORECASE),
    re.compile(r'token limit exceeded', re.IGNORECASE),
)

_CONTEXT_OVERFLOW_EXCLUSIONS = (
    re.compile(r'rate limit', re.IGNORECASE),
    re.compile(r'too many requests', re.IGNORECASE),
    re.compile(r'throttl', re.IGNORECASE),
    re.compile(r'quota', re.IGNORECASE),
    re.compile(r'billing', re.IGNORECASE),
    re.compile(r'per (?:minute|hour|day)', re.IGNORECASE),
)


def _trim_tail(messages: list[Message]) -> list[Message] | None:
    if len(messages) <= 1:
        return None
    return messages[: max(1, len(messages) // 2)]


def _compact_messages(messages: Sequence[HistoryMessage]) -> list[Message]:
    compacted: list[Message] = []
    for message in messages:
        if isinstance(message, SummaryMessage):
            compacted.append(message.to_message())
        elif isinstance(message, UserMessage):
            if message.content.strip():
                compacted.append(replace(message, images=[]))
        elif isinstance(message, AssistantMessage) and message.content.strip():
            compacted.append(replace(message, tool_calls=None, reasoning_content=None))
    return compacted


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
            new_messages, error = await core.chat(provider, [UserMessage(content)], [GentTilte()], [])
            if error is None:
                session.title = new_messages[-1].content
                await self.session_mgr.save(session.uuid)
            else:
                await self.report_failure(core, provider)
        return session

    def is_context_overflow(self, error: Exception) -> bool:
        if not isinstance(error, APIError):
            return False
        if getattr(error, 'status_code', None) == 413:
            return True
        body = error.body
        if not isinstance(body, dict):
            return False
        raw = body.get('error')
        message = ''
        code = ''
        if isinstance(raw, dict):
            value = raw.get('message')
            message = value if isinstance(value, str) else ''
            value = raw.get('code')
            code = value if isinstance(value, str) else ''
        elif isinstance(raw, str):
            message = raw
        if code.lower() == 'context_length_exceeded':
            return True
        if not message:
            return False
        if any(pattern.search(message) for pattern in _CONTEXT_OVERFLOW_EXCLUSIONS):
            return False
        return any(pattern.search(message) for pattern in _CONTEXT_OVERFLOW_PATTERNS)

    def needs_compression(self, messages: Sequence[Message], provider: Provider) -> bool:
        for message in reversed(messages):
            if isinstance(message, AssistantMessage) and message.usage is not None:
                tokens = message.usage.total_tokens or message.usage.prompt_tokens
                return tokens >= int(provider.context_window * _COMPRESSION_RATIO)
        return False

    async def get_summary(self, messages: Sequence[HistoryMessage]) -> SummaryMessage | None:
        trimmed = _compact_messages(messages)
        if not trimmed:
            return None
        core = AgentCore('Compact')
        provider = self.provider_mgr.provider
        while trimmed:
            new_messages, error = await core.chat(provider, trimmed, [CompactContext()], [])
            if error is None and new_messages:
                return SummaryMessage(new_messages[-1].content)
            shrunk = _trim_tail(trimmed)
            if shrunk is None:
                break
            trimmed = shrunk
        return None
