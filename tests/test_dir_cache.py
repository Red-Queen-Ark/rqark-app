import json
from pathlib import Path

from rqark_app.config.dir_cache import DirCache

HASH = 'aaaa1111bbbb'
OTHER = 'cccc2222dddd'


def make_cache(tmp_path: Path) -> DirCache:
    return DirCache(tmp_path)


def stored(tmp_path: Path) -> dict[str, list[str]]:
    return json.loads((tmp_path / 'dir_caches.json').read_text(encoding='utf-8'))


def test_an_unknown_directory_has_no_sessions(tmp_path: Path):
    cache = make_cache(tmp_path)
    assert cache.get_session_ids(HASH) == []
    assert cache.get_session_id(HASH) is None


def test_a_session_is_remembered_until_it_is_forgotten(tmp_path: Path):
    cache = make_cache(tmp_path)
    cache.set_session_id(HASH, 'session-a')
    assert cache.get_session_ids(HASH) == ['session-a']
    assert cache.get_session_id(HASH) == 'session-a'
    cache.remove_session_id(HASH, 'session-a')
    assert cache.get_session_ids(HASH) == []
    assert cache.get_session_id(HASH) is None


def test_a_directory_keeps_several_sessions(tmp_path: Path):
    cache = make_cache(tmp_path)
    cache.set_session_id(HASH, 'session-a')
    cache.set_session_id(HASH, 'session-b')
    cache.set_session_id(HASH, 'session-c')
    assert cache.get_session_ids(HASH) == ['session-c', 'session-b', 'session-a']


def test_the_most_recently_used_session_comes_first(tmp_path: Path):
    cache = make_cache(tmp_path)
    cache.set_session_id(HASH, 'session-a')
    cache.set_session_id(HASH, 'session-b')
    cache.set_session_id(HASH, 'session-a')
    assert cache.get_session_ids(HASH) == ['session-a', 'session-b']
    assert cache.get_session_id(HASH) == 'session-a'


def test_recording_a_session_twice_does_not_duplicate_it(tmp_path: Path):
    cache = make_cache(tmp_path)
    cache.set_session_id(HASH, 'session-a')
    cache.set_session_id(HASH, 'session-b')
    cache.set_session_id(HASH, 'session-c')
    cache.set_session_id(HASH, 'session-c')
    assert cache.get_session_ids(HASH) == ['session-c', 'session-b', 'session-a']


def test_directories_are_kept_apart(tmp_path: Path):
    cache = make_cache(tmp_path)
    cache.set_session_id(HASH, 'session-a')
    cache.set_session_id(OTHER, 'session-b')
    assert cache.get_session_ids(HASH) == ['session-a']
    assert cache.get_session_ids(OTHER) == ['session-b']
    cache.remove_session_id(HASH, 'session-a')
    assert cache.get_session_ids(OTHER) == ['session-b']


def test_forgetting_one_session_keeps_the_others(tmp_path: Path):
    cache = make_cache(tmp_path)
    cache.set_session_id(HASH, 'session-a')
    cache.set_session_id(HASH, 'session-b')
    cache.remove_session_id(HASH, 'session-a')
    assert cache.get_session_ids(HASH) == ['session-b']
    assert stored(tmp_path) == {HASH: ['session-b']}


def test_forgetting_the_last_session_drops_the_directory(tmp_path: Path):
    cache = make_cache(tmp_path)
    cache.set_session_id(HASH, 'session-a')
    cache.remove_session_id(HASH, 'session-a')
    assert HASH not in stored(tmp_path)


def test_forgetting_an_unknown_session_changes_nothing(tmp_path: Path):
    cache = make_cache(tmp_path)
    cache.set_session_id(HASH, 'session-a')
    cache.remove_session_id(HASH, 'session-other')
    cache.remove_session_id(OTHER, 'session-a')
    assert stored(tmp_path) == {HASH: ['session-a']}


def test_session_ids_survive_a_reload(tmp_path: Path):
    make_cache(tmp_path).set_session_id(HASH, 'session-a')
    make_cache(tmp_path).set_session_id(HASH, 'session-b')
    assert make_cache(tmp_path).get_session_ids(HASH) == ['session-b', 'session-a']


def test_an_id_written_by_an_older_version_is_read_as_one_session(tmp_path: Path):
    (tmp_path / 'dir_caches.json').write_text(json.dumps({HASH: 'session-a'}), encoding='utf-8')
    cache = make_cache(tmp_path)
    assert cache.get_session_ids(HASH) == ['session-a']
    cache.set_session_id(HASH, 'session-b')
    assert stored(tmp_path) == {HASH: ['session-b', 'session-a']}


def test_an_unreadable_cache_is_treated_as_empty(tmp_path: Path):
    (tmp_path / 'dir_caches.json').write_text('not json at all', encoding='utf-8')
    cache = make_cache(tmp_path)
    assert cache.get_session_ids(HASH) == []
    cache.set_session_id(HASH, 'session-a')
    assert cache.get_session_ids(HASH) == ['session-a']


def test_entries_of_the_wrong_shape_are_ignored(tmp_path: Path):
    (tmp_path / 'dir_caches.json').write_text(json.dumps({HASH: 42, OTHER: [1, 'session-a', None]}), encoding='utf-8')
    cache = make_cache(tmp_path)
    assert cache.get_session_ids(HASH) == []
    assert cache.get_session_ids(OTHER) == ['session-a']


def test_the_file_is_created_on_demand(tmp_path: Path):
    assert not (tmp_path / 'dir_caches.json').exists()
    make_cache(tmp_path).get_session_ids(HASH)
    assert not (tmp_path / 'dir_caches.json').exists()


def test_compute_hash_normalizes_the_path(tmp_path: Path):
    nested = tmp_path / 'project'
    nested.mkdir()
    assert DirCache.compute_hash(nested) == DirCache.compute_hash(nested / '.' / '..' / 'project')
    assert DirCache.compute_hash(nested) == DirCache.compute_hash(str(nested))
    assert len(DirCache.compute_hash(nested)) == 12
    assert DirCache.compute_hash(nested) != DirCache.compute_hash(tmp_path)
