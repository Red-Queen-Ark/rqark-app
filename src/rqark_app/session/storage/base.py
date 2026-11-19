from abc import ABC, abstractmethod
from collections.abc import Sequence

from rqark_app.types.session import Session


class SessionStorage(ABC):
    @abstractmethod
    async def create(self, session: Session) -> None: ...

    @abstractmethod
    async def save(self, session: Session) -> None: ...

    @abstractmethod
    async def load(self, ids: Sequence[str] | None = None) -> list[Session]:
        """Read the stored sessions.

        ``ids`` limits the read to those session ids: a caller that already knows
        which sessions it wants does not pay for the rest, which in the cloud means
        one message fetch per session. ``None`` reads everything.
        """
        ...

    @abstractmethod
    async def delete(self, session_id: str) -> bool: ...
