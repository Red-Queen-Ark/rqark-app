from rqark_core.types.tool import PlanItem

from rqark_app.session.storage import SessionStorage
from rqark_app.types.session import Session


class SessionManager:
    def __init__(self, storage: SessionStorage | None = None):
        self.storage = storage
        self.sessions_map: dict[str, Session] = {}

    async def create(self, session_id: str | None = None) -> Session:
        session = Session() if session_id is None else Session(uuid=session_id)
        self.sessions_map[session.uuid] = session
        return session

    async def get_or_create(self, session_id: str) -> Session:
        if session_id in self.sessions_map:
            return self.sessions_map[session_id]
        return await self.create(session_id)

    async def set_plan(self, agent_id: str, items: list[PlanItem]) -> Session | None:
        session_id = agent_id.rsplit(':', 1)[-1]
        session = self.sessions_map.get(session_id)
        if session is None:
            return None
        session.plan_items = list(items)
        return session

    async def delete(self, session_id: str) -> None:
        if self.storage:
            await self.storage.delete(session_id)
        self.sessions_map.pop(session_id, None)

    async def get(self, session_id: str) -> Session | None:
        return self.sessions_map.get(session_id, None)

    async def revert(self, session_id: str, message_id: str) -> Session | None:
        session = self.sessions_map.get(session_id)
        if session is None:
            return None
        if session.revert_to(message_id) is None:
            return None
        await self.save(session_id)
        return session

    async def load(self):
        if self.storage:
            sessions = await self.storage.load()
            self.sessions_map = {s.uuid: s for s in sessions}

    async def save(self, session_id: str):
        session = await self.get(session_id)
        if self.storage and session:
            await self.storage.save(session)
