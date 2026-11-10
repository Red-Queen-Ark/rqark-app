import threading
from pathlib import Path

from rqark_core.types.chat import UserMessage

from rqark_app.session.storage import JSONLStorage
from rqark_app.types.session import Session


async def test_jsonl_storage_writes_and_reads_off_the_event_loop(tmp_path, monkeypatch):
    storage = JSONLStorage(tmp_path)
    loop_thread = threading.get_ident()
    threads = []
    real_write = Path.write_text

    def record(path, *args, **kwargs):
        threads.append(threading.get_ident())
        return real_write(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'write_text', record)

    session = Session()
    session.history.append(UserMessage('hi'))
    await storage.create(session)

    assert threads
    assert all(thread is not loop_thread for thread in threads)

    loaded = await storage.load()
    assert [m.content for m in loaded[0].history] == ['hi']


async def test_jsonl_storage_delete_reports_whether_the_file_existed(tmp_path):
    storage = JSONLStorage(tmp_path)
    session = Session()
    await storage.create(session)

    assert await storage.delete(session.uuid) is True
    assert await storage.delete(session.uuid) is False


async def test_jsonl_storage_load_skips_empty_files(tmp_path):
    (tmp_path / 'empty.jsonl').write_text('\n\n', encoding='utf-8')
    assert await JSONLStorage(tmp_path).load() == []
