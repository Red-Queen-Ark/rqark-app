import asyncio
from pathlib import Path

from rqark_app.session.storage import JSONLStorage
from rqark_app.types.session import Session


def test_loading_only_the_given_ids_reads_only_those_files(tmp_path: Path):
    storage = JSONLStorage(tmp_path)
    for session_id in ('a', 'b', 'c'):
        asyncio.run(storage.save(Session(uuid=session_id)))

    sessions = asyncio.run(storage.load(['a', 'c']))

    assert sorted(session.uuid for session in sessions) == ['a', 'c']


def test_loading_with_no_ids_reads_nothing(tmp_path: Path):
    storage = JSONLStorage(tmp_path)
    asyncio.run(storage.save(Session(uuid='a')))

    assert asyncio.run(storage.load([])) == []


def test_loading_without_ids_reads_everything(tmp_path: Path):
    storage = JSONLStorage(tmp_path)
    for session_id in ('a', 'b'):
        asyncio.run(storage.save(Session(uuid=session_id)))

    assert sorted(session.uuid for session in asyncio.run(storage.load())) == ['a', 'b']
