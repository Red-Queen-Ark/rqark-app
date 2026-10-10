from collections.abc import Sequence

from rqark_core.core import AgentCore
from rqark_core.types.chat import AssistantMessage, Message
from rqark_core.types.provider import Provider

from rqark_app.compact.messages import compact_messages, trim_tail
from rqark_app.compact.prompt import CompactContext
from rqark_app.provider.manager import ProviderManager
from rqark_app.types.session import HistoryMessage, SummaryMessage

_COMPRESSION_RATIO = 0.8


class Compactor:
    def __init__(self, provider_mgr: ProviderManager):
        self.provider_mgr = provider_mgr

    @staticmethod
    def needs_compression(messages: Sequence[Message], provider: Provider) -> bool:
        for message in reversed(messages):
            if isinstance(message, AssistantMessage) and message.usage is not None:
                tokens = message.usage.total_tokens or message.usage.prompt_tokens
                return tokens >= int(provider.context_window * _COMPRESSION_RATIO)
        return False

    async def get_summary(self, messages: Sequence[HistoryMessage]) -> SummaryMessage | None:
        trimmed = compact_messages(messages)
        if not trimmed:
            return None
        core = AgentCore('Compact')
        provider = self.provider_mgr.provider
        while trimmed:
            new_messages, error = await core.chat(provider, trimmed, [CompactContext()], [])
            if error is None and new_messages:
                return SummaryMessage(new_messages[-1].content)
            shrunk = trim_tail(trimmed)
            if shrunk is None:
                break
            trimmed = shrunk
        return None
