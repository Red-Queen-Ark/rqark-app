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
    id: str = field(default_factory=lambda: str(uuid4()))

    def to_dict(self) -> dict:
        return {'role': self.role, 'content': self.content, 'id': self.id}

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

    def revert_to(self, message_id: str) -> list[HistoryMessage] | None:
        index = next((i for i, m in enumerate(self.history) if m.id == message_id), None)
        if index is None or not isinstance(self.history[index], UserMessage):
            return None
        if sum(isinstance(m, UserMessage) for m in self.history) <= 1:
            return None
        removed = self.history[index:]
        self.history = self.history[:index]
        return removed

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


def _created_at_from(data: dict) -> datetime:
    raw = data.get('created_at')
    return parse_dt(raw) if raw else datetime.now(UTC)


def _id_from(data: dict) -> str:
    raw = data.get('id')
    return raw if isinstance(raw, str) and raw else str(uuid4())


def _text_part(part: dict) -> str | None:
    value = part.get('text')
    return value if isinstance(value, str) else None


def _image_part(part: dict) -> str | None:
    url = part.get('image_url')
    if not isinstance(url, dict):
        return None
    value = url.get('url')
    return value if isinstance(value, str) else None


def _user_parts(content: object) -> tuple[str, list[str]]:
    if isinstance(content, str):
        return content, []
    if not isinstance(content, list):
        return '', []
    text: list[str] = []
    images: list[str] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        match part.get('type'):
            case 'text':
                if (value := _text_part(part)) is not None:
                    text.append(value)
            case 'image_url':
                if (value := _image_part(part)) is not None:
                    images.append(value)
    return '\n'.join(text), images


def message_from_dict(data: dict) -> HistoryMessage:
    match data['role']:
        case 'user':
            content, images = _user_parts(data['content'])
            return UserMessage(content=content, images=images, created_at=_created_at_from(data), id=_id_from(data))
        case 'summary':
            return SummaryMessage(content=data['content'], id=_id_from(data))
        case 'assistant':
            tool_calls = [ToolCall(id=tc['id'], type=tc['type'], name=tc['function']['name'], arguments=tc['function']['arguments']) for tc in data['tool_calls']] if data.get('tool_calls') else None
            usage = Usage(**data['usage']) if data.get('usage') else None
            return AssistantMessage(content=data['content'], tool_calls=tool_calls, reasoning_content=data.get('reasoning_content'), usage=usage, created_at=_created_at_from(data), id=_id_from(data))
        case 'tool':
            return ToolMessage(tool_call_id=data['tool_call_id'], content=data['content'], tool_name=data.get('tool_name'), arguments=data.get('arguments'), created_at=_created_at_from(data), id=_id_from(data))
        case _:
            return SystemMessage(content=data['content'], created_at=_created_at_from(data), id=_id_from(data))
