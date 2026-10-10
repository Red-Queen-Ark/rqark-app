from collections.abc import Sequence
from dataclasses import replace

from rqark_core.types.chat import AssistantMessage, Message, UserMessage

from rqark_app.types.session import HistoryMessage, SummaryMessage


def trim_tail(messages: list[Message]) -> list[Message] | None:
    if len(messages) <= 1:
        return None
    return messages[: max(1, len(messages) - 1)]


def compact_messages(messages: Sequence[HistoryMessage]) -> list[Message]:
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
