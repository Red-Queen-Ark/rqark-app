from rqark_core.types.tool import PlanItem
from rqark_app.types.session import ChatMessage

class Session:
    uuid: str
    title: str = ''
    plan_items: list[PlanItem] = []
    chats: list[ChatMessage] = []

class SessionManager:
    def __init__(self):
        self.sessions = []
