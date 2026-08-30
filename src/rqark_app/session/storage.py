import json
from abc import ABC, abstractmethod
from pathlib import Path

from rqark_app.types.session import Session, message_from_dict


class SessionStorage(ABC):
    @abstractmethod
    async def create(self, session: Session) -> None: ...

    @abstractmethod
    async def save(self, session: Session) -> None: ...

    @abstractmethod
    async def load(self) -> list[Session]: ...

    @abstractmethod
    async def delete(self, session_id: str) -> bool: ...


class JSONLStorage(SessionStorage):
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _file_path(self, session_id: str) -> Path:
        return self.path / f'{session_id}.jsonl'

    async def create(self, session: Session) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        self._write_file(session)

    async def save(self, session: Session) -> None:
        self._write_file(session)

    async def load(self) -> list[Session]:
        if not self.path.exists():
            return []
        sessions: list[Session] = []
        for file_path in self.path.glob('*.jsonl'):
            lines = [line.strip() for line in file_path.read_text(encoding='utf-8').splitlines() if line.strip()]
            if not lines:
                continue
            session = Session.from_dict(json.loads(lines[0]))
            session.history = [message_from_dict(json.loads(line)) for line in lines[1:]]
            sessions.append(session)
        return sessions

    async def delete(self, session_id: str) -> bool:
        file_path = self._file_path(session_id)
        if not file_path.exists():
            return False
        file_path.unlink()
        return True

    def _write_file(self, session: Session) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        data = session.to_dict()
        history = data.pop('history')
        lines = [json.dumps(data, ensure_ascii=False)]
        lines.extend(json.dumps(m, ensure_ascii=False) for m in history)
        self._file_path(session.uuid).write_text('\n'.join(lines) + '\n', encoding='utf-8')
