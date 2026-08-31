from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from rqark_core.types.chat import AssistantMessage, Message, SystemMessage, ToolCall, ToolMessage, Usage, UserMessage
from rqark_core.types.tool import PlanItem

type HistoryMessage = Message | SummaryMessage

@dataclass
class SummaryMessage:
    content: str
    role: Literal['summary'] = 'summary'

    def to_dict(self) -> dict:
        return {'role': self.role, 'content': self.content}

    def to_message(self) -> UserMessage:
        return UserMessage(self.content)

@dataclass
class Session:
    uuid: str = field(default_factory=lambda: str(uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    title: str = ''
    plan_items: list[PlanItem] = field(default_factory=list)
    history: list[HistoryMessage] = field(default_factory=list)

    @property
    def history_chunk(self) -> list[list[HistoryMessage]]:
        chunks: list[list[HistoryMessage]] = []
        current: list[HistoryMessage] = []
        for m in self.history:
            if isinstance(m, SummaryMessage) and current:
                chunks.append(current)
                current = []
            current.append(m)
        if current:
            chunks.append(current)
        return chunks

    def get_last_chunk_for_chat(self) -> list[Message]:
        return [ m.to_message() if isinstance(m, SummaryMessage) else m for m in self.get_last_chunk() ]

    def get_last_chunk(self) -> list[HistoryMessage]:
        chunks = self.history_chunk
        return chunks[-1] if chunks else []

    def update_history_to_last_chunk(self, messages: list[Message]):
        chunks = self.history_chunk
        if not chunks:
            self.history = list(messages)
            return
        chunks[-1][1:] = messages[1:]
        self.history = [m for chunk in chunks for m in chunk]
    def to_dict(self) -> dict:
        return {
            'uuid': self.uuid,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'title': self.title,
            'plan_items': [asdict(p) for p in self.plan_items],
            'history': [m.to_dict() for m in self.history],
        }

    @classmethod
    def from_dict(cls, data: dict) -> Session:
        return cls(
            uuid=data['uuid'],
            created_at=parse_dt(data['created_at']),
            updated_at=parse_dt(data['updated_at']),
            title=data.get('title', ''),
            plan_items=[PlanItem(**p) for p in data.get('plan_items', [])],
            history=[message_from_dict(m) for m in data.get('history', [])],
        )


def parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def message_from_dict(data: dict) -> HistoryMessage:
    match data['role']:
        case 'user':
            return UserMessage(content=data['content'])
        case 'summary':
            return SummaryMessage(content=data['content'])
        case 'assistant':
            tool_calls = [ToolCall(id=tc['id'], type=tc['type'], name=tc['function']['name'], arguments=tc['function']['arguments']) for tc in data['tool_calls']] if data.get('tool_calls') else None
            usage = Usage(**data['usage']) if data.get('usage') else None
            return AssistantMessage(content=data['content'], tool_calls=tool_calls, reasoning_content=data.get('reasoning_content'), usage=usage)
        case 'tool':
            return ToolMessage(tool_call_id=data['tool_call_id'], content=data['content'], tool_name=data.get('tool_name'), arguments=data.get('arguments'))
        case _:
            return SystemMessage(content=data['content'])
