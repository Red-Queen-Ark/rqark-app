from datetime import datetime
from uuid import uuid4

from rqark_core.types.chat import Message
from rqark_core.types.tool import PlanItem


class ChatMessage:
    def __init__(self, message: Message):
        self.uuid = str(uuid4())
        self.datetime: str = datetime.now().isoformat()
        self.message: Message = message

    def to_dict(self):
        return {
            'uuid': self.uuid,
            'datetime': self.datetime,
            **self.message.to_dict()
        }


class Session:
    uuid: str
    title: str = ''
    plan_items: list[PlanItem] = []
    chats: list[ChatMessage] = []
