from abc import ABC, abstractmethod

from rqark_app.types.session import Session


class SessionStorage(ABC):
    @abstractmethod
    async def create(self, session: Session) -> None: ...

    @abstractmethod
    async def save(self, session: Session) -> None: ...

    @abstractmethod
    async def load(self) -> list[Session]: ...

    @abstractmethod
    async def delete(self, session_id: str) -> bool: ...
