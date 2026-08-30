from dataclasses import asdict, dataclass, field
from datetime import datetime
from uuid import uuid4

from rqark_core.types.chat import AssistantMessage, Message, SystemMessage, ToolCall, ToolMessage, Usage, UserMessage
from rqark_core.types.tool import PlanItem


@dataclass
class Session:
    agent_id: str
    path: tuple[str, ...] = ()
    uuid: str = field(default_factory=lambda: str(uuid4()))
    title: str = ''
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    history: list[Message] = field(default_factory=list)
    plan_items: list[PlanItem] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            'uuid': self.uuid,
            'agent_id': self.agent_id,
            'path': list(self.path),
            'title': self.title,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'history': [m.to_dict() for m in self.history],
            'plan_items': [asdict(p) for p in self.plan_items],
        }

    @classmethod
    def from_dict(cls, data: dict) -> Session:
        return cls(
            agent_id=data['agent_id'],
            path=tuple(data.get('path', [])),
            uuid=data['uuid'],
            title=data.get('title', ''),
            created_at=datetime.fromisoformat(data['created_at']),
            updated_at=datetime.fromisoformat(data['updated_at']),
            history=[message_from_dict(m) for m in data.get('history', [])],
            plan_items=[PlanItem(**p) for p in data.get('plan_items', [])],
        )


def message_from_dict(data: dict) -> Message:
    match data['role']:
        case 'user':
            return UserMessage(content=data['content'])
        case 'assistant':
            tool_calls = [
                ToolCall(id=tc['id'], type=tc['type'], name=tc['function']['name'], arguments=tc['function']['arguments'])
                for tc in data['tool_calls']
            ] if data.get('tool_calls') else None
            usage = Usage(**data['usage']) if data.get('usage') else None
            return AssistantMessage(content=data['content'], tool_calls=tool_calls, reasoning_content=data.get('reasoning_content'), usage=usage)
        case 'tool':
            return ToolMessage(tool_call_id=data['tool_call_id'], content=data['content'], tool_name=data.get('tool_name'), arguments=data.get('arguments'))
        case _:
            return SystemMessage(content=data['content'])
