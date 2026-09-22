import hashlib
import json
import threading
from pathlib import Path


class DirCache:
    """Maps working-directory hash → the session ids of that directory, most recent first.

    A directory keeps every conversation started in it, so reopening a project can
    restore them all; ``get_session_id`` still returns the single most recently used
    one for callers that only resume a session.
    """

    def __init__(self, cache_path: Path) -> None:
        self._path = cache_path / 'dir_caches.json'
        self._lock = threading.Lock()

    def _load(self) -> dict[str, list[str]]:
        try:
            if self._path.exists():
                return {dir_hash: self._ids(value) for dir_hash, value in json.loads(self._path.read_text(encoding='utf-8')).items()}
        except Exception:
            pass
        return {}

    @staticmethod
    def _ids(value: object) -> list[str]:
        """The session ids recorded for one directory: a lone id in the old format, a list since."""
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            return [item for item in value if isinstance(item, str)]
        return []

    def _save(self, data: dict[str, list[str]]) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self._path.with_suffix('.tmp')
            tmp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
            tmp_path.replace(self._path)
        except OSError:
            pass

    def get_session_ids(self, dir_hash: str) -> list[str]:
        """Every session of the directory, most recently used first."""
        with self._lock:
            return list(self._load().get(dir_hash, []))

    def get_session_id(self, dir_hash: str) -> str | None:
        """The most recently used session of the directory, or None."""
        session_ids = self.get_session_ids(dir_hash)
        return session_ids[0] if session_ids else None

    def set_session_id(self, dir_hash: str, session_id: str) -> None:
        """Record a session as the directory's most recently used one."""
        with self._lock:
            data = self._load()
            data[dir_hash] = [session_id, *(other for other in data.get(dir_hash, []) if other != session_id)]
            self._save(data)

    def remove_session_id(self, dir_hash: str, session_id: str) -> None:
        """Forget a session of the directory, once its stored transcript is gone."""
        with self._lock:
            data = self._load()
            session_ids = data.get(dir_hash, [])
            if session_id not in session_ids:
                return
            remaining = [other for other in session_ids if other != session_id]
            if remaining:
                data[dir_hash] = remaining
            else:
                del data[dir_hash]
            self._save(data)

    @staticmethod
    def compute_hash(cwd: str | Path) -> str:
        normalized = Path(cwd).resolve()
        return hashlib.sha256(str(normalized).encode()).hexdigest()[:12]
