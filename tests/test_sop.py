from pathlib import Path

import pytest

from rqark_app.cloud.client import DataCloudError
from rqark_app.sop import Sop, SopManager, expand
from rqark_app.sop.types import CLOUD_SOURCE, LOCAL_SOURCE


class FakeCloud:
    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.created: list[dict] = []
        self.updated: list[tuple] = []
        self.deleted: list[str] = []
        self.failure: DataCloudError | None = None

    def _raise(self) -> None:
        if self.failure is not None:
            raise self.failure

    async def list_sops(self) -> list[dict]:
        self._raise()
        return self.rows

    async def get_sop(self, slug: str) -> dict:
        self._raise()
        row = next((row for row in self.rows if row['slug'] == slug), None)
        if row is None:
            raise DataCloudError(404, 'NOT_FOUND', 'Sop not found.')
        return row

    async def create_sop(self, payload: dict) -> dict:
        self._raise()
        self.created.append(payload)
        return {**payload, 'title': payload.get('title') or 'cloud title'}

    async def update_sop(self, slug: str, payload: dict) -> dict:
        self._raise()
        row = next((row for row in self.rows if row['slug'] == slug), None)
        if row is None:
            raise DataCloudError(404, 'NOT_FOUND', 'Sop not found.')
        self.updated.append((slug, payload))
        return {**row, **payload}

    async def delete_sop(self, slug: str) -> None:
        self._raise()
        if not any(row['slug'] == slug for row in self.rows):
            raise DataCloudError(404, 'NOT_FOUND', 'Sop not found.')
        self.deleted.append(slug)


def write_local(root: Path, slug: str, content: str) -> None:
    path = root / 'sop'
    path.mkdir(parents=True, exist_ok=True)
    (path / f'{slug}.md').write_text(content, encoding='utf-8')


async def test_list_reads_both_sources_and_local_wins(tmp_path: Path):
    write_local(tmp_path, 'shared', '# Local version\n')
    write_local(tmp_path, 'only-local', '# Local only\n')
    cloud = FakeCloud()
    cloud.rows = [{'slug': 'shared', 'title': 'Cloud version', 'content': '# Cloud version\n'}, {'slug': 'only-cloud', 'title': 'Cloud only', 'content': '# Cloud only\n'}]

    sops = await SopManager(tmp_path, cloud).list()

    assert [sop.slug for sop in sops] == ['only-cloud', 'only-local', 'shared']
    assert {sop.slug: sop for sop in sops}['shared'].content == '# Local version\n'
    assert {sop.slug: sop for sop in sops}['shared'].source == LOCAL_SOURCE


async def test_list_ignores_a_cloud_failure(tmp_path: Path):
    write_local(tmp_path, 'only-local', '# Local only\n')
    cloud = FakeCloud()
    cloud.failure = DataCloudError(0, 'REQUEST_FAILED', 'cannot reach data cloud')

    sops = await SopManager(tmp_path, cloud).list()

    assert [sop.slug for sop in sops] == ['only-local']


async def test_list_without_either_source_is_empty(tmp_path: Path):
    assert await SopManager(tmp_path).list() == []


async def test_local_titles_come_from_the_first_heading(tmp_path: Path):
    write_local(tmp_path, 'heading', '\n# Trip itinerary\n\nPlan it.\n')
    write_local(tmp_path, 'plain', 'Plan it day by day.\n')

    sops = {sop.slug: sop for sop in await SopManager(tmp_path).list()}

    assert sops['heading'].title == 'Trip itinerary'
    assert sops['plain'].title == 'plain'


@pytest.mark.parametrize('slug', ['', '../escape', 'Trip', 'with space', '-leading', 'has_underscore', 'a' * 65])
async def test_local_save_rejects_a_slug_off_the_whitelist(tmp_path: Path, slug: str):
    with pytest.raises(ValueError):
        await SopManager(tmp_path).save(slug, '# hi')


@pytest.mark.parametrize('length', [1999, 2000])
async def test_local_save_accepts_content_up_to_the_limit(tmp_path: Path, length: int):
    sop = await SopManager(tmp_path).save('edge', '字' * length)

    assert len(sop.content) == length


async def test_local_save_rejects_content_over_the_limit(tmp_path: Path):
    with pytest.raises(ValueError):
        await SopManager(tmp_path).save('too-long', '字' * 2001)


async def test_save_without_a_cloud_writes_a_local_file(tmp_path: Path):
    manager = SopManager(tmp_path)

    await manager.save('trip-itinerary', '# Trip itinerary\n')

    assert (tmp_path / 'sop' / 'trip-itinerary.md').read_text(encoding='utf-8') == '# Trip itinerary\n'
    assert await manager.get('trip-itinerary') is not None


async def test_save_with_a_cloud_writes_to_the_cloud(tmp_path: Path):
    cloud = FakeCloud()
    cloud.rows = [{'slug': 'trip-itinerary', 'title': 'Trip itinerary', 'content': '# Old\n'}]

    sop = await SopManager(tmp_path, cloud).save('trip-itinerary', '# New\n')

    assert cloud.updated == [('trip-itinerary', {'content': '# New\n'})]
    assert cloud.created == []
    assert sop.content == '# New\n'
    assert not (tmp_path / 'sop' / 'trip-itinerary.md').exists()


async def test_save_creates_the_sop_on_the_cloud_when_it_is_missing(tmp_path: Path):
    cloud = FakeCloud()

    sop = await SopManager(tmp_path, cloud).save('trip-itinerary', '# New\n')

    assert cloud.created == [{'slug': 'trip-itinerary', 'content': '# New\n'}]
    assert cloud.updated == []
    assert sop.slug == 'trip-itinerary'


async def test_save_propagates_a_cloud_failure_other_than_not_found(tmp_path: Path):
    cloud = FakeCloud()
    cloud.failure = DataCloudError(400, 'INVALID_CONTENT', 'content must be at most 2000 characters.')

    with pytest.raises(DataCloudError):
        await SopManager(tmp_path, cloud).save('trip-itinerary', '# New\n')


async def test_delete_removes_the_local_file(tmp_path: Path):
    write_local(tmp_path, 'trip-itinerary', '# Trip\n')

    assert await SopManager(tmp_path).delete('trip-itinerary') is True
    assert await SopManager(tmp_path).delete('trip-itinerary') is False


async def test_delete_with_a_cloud_deletes_there(tmp_path: Path):
    cloud = FakeCloud()
    cloud.rows = [{'slug': 'trip-itinerary', 'title': 'Trip', 'content': '# Trip\n'}]
    manager = SopManager(tmp_path, cloud)

    assert await manager.delete('trip-itinerary') is True
    assert cloud.deleted == ['trip-itinerary']


async def test_delete_reports_a_missing_cloud_sop(tmp_path: Path):
    cloud = FakeCloud()

    assert await SopManager(tmp_path, cloud).delete('trip-itinerary') is False


async def test_get_prefers_the_local_file(tmp_path: Path):
    write_local(tmp_path, 'shared', '# Local\n')
    cloud = FakeCloud()
    cloud.rows = [{'slug': 'shared', 'title': 'Cloud', 'content': '# Cloud\n'}]

    sop = await SopManager(tmp_path, cloud).get('shared')

    assert sop is not None and sop.source == LOCAL_SOURCE


async def test_get_reads_a_cloud_only_sop(tmp_path: Path):
    cloud = FakeCloud()
    cloud.rows = [{'slug': 'cloud-only', 'title': 'Cloud', 'content': '# Cloud\n'}]

    sop = await SopManager(tmp_path, cloud).get('cloud-only')

    assert sop is not None and sop.source == CLOUD_SOURCE


def test_expand_rewrites_the_message_and_keeps_the_arguments():
    sops = [Sop('trip-itinerary', 'Trip itinerary', '# Trip itinerary\n\nPlan it.', LOCAL_SOURCE)]

    expanded = expand('/trip-itinerary 幫我安排大阪行程', sops)

    assert expanded == ('#trip-itinerary 幫我安排大阪行程\n\n# Trip itinerary\n\nPlan it.', 'trip-itinerary')


def test_expand_without_arguments_keeps_only_the_tag():
    sops = [Sop('trip-itinerary', 'Trip itinerary', '# Trip itinerary', LOCAL_SOURCE)]

    expanded = expand('/trip-itinerary', sops)

    assert expanded == ('#trip-itinerary\n\n# Trip itinerary', 'trip-itinerary')


def test_expand_returns_none_for_an_unknown_slug():
    assert expand('/nope', []) is None


def test_expand_returns_none_for_a_message_that_merely_starts_with_a_slash():
    sops = [Sop('trip', 'Trip', '# Trip', LOCAL_SOURCE)]

    assert expand('hello /trip', sops) is None


def test_expand_returns_none_for_the_bare_slash():
    assert expand('/', []) is None
