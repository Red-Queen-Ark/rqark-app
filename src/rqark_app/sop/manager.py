from pathlib import Path

from rqark_app.cloud.client import DataCloudError, RQArkDataCloudClient
from rqark_app.sop.types import CLOUD_SOURCE, LOCAL_SOURCE, MAX_CONTENT, SLUG_PATTERN, SLUG_PATTERN_HINT, Sop, title_of

SopList = list[Sop]


class SopManager:
    def __init__(self, config_path: str | Path, cloud_client: RQArkDataCloudClient | None = None):
        self.dir = Path(config_path) / 'sop'
        self.cloud_client = cloud_client

    async def list(self) -> SopList:
        sops = {sop.slug: sop for sop in await self._cloud()}
        for sop in self._local():
            sops[sop.slug] = sop
        return [sops[slug] for slug in sorted(sops)]

    async def get(self, slug: str) -> Sop | None:
        local = self._read_local(slug)
        if local is not None:
            return local
        return await self._read_cloud(slug)

    async def save(self, slug: str, content: str) -> Sop:
        validate(slug, content)
        if self.cloud_client is not None:
            return await self._save_cloud(slug, content)
        return self._save_local(slug, content)

    async def delete(self, slug: str) -> bool:
        if not SLUG_PATTERN.match(slug):
            raise ValueError(SLUG_PATTERN_HINT)
        if self.cloud_client is not None:
            return await self._delete_cloud(slug)
        return self._delete_local(slug)

    def _local(self) -> SopList:
        if not self.dir.is_dir():
            return []
        sops: list[Sop] = []
        for path in sorted(self.dir.glob('*.md')):
            sop = self._read_local(path.stem)
            if sop is not None:
                sops.append(sop)
        return sops

    def _read_local(self, slug: str) -> Sop | None:
        if not SLUG_PATTERN.match(slug):
            return None
        path = self.dir / f'{slug}.md'
        try:
            content = path.read_text(encoding='utf-8')
        except OSError:
            return None
        return Sop(slug, title_of(content, slug), content, LOCAL_SOURCE)

    def _save_local(self, slug: str, content: str) -> Sop:
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / f'{slug}.md').write_text(content, encoding='utf-8')
        return Sop(slug, title_of(content, slug), content, LOCAL_SOURCE)

    def _delete_local(self, slug: str) -> bool:
        path = self.dir / f'{slug}.md'
        if not path.is_file():
            return False
        path.unlink()
        return True

    async def _cloud(self) -> SopList:
        if self.cloud_client is None:
            return []
        try:
            rows = await self.cloud_client.list_sops()
        except DataCloudError:
            return []
        return [sop for sop in (self._from_row(row) for row in rows) if sop is not None]

    async def _read_cloud(self, slug: str) -> Sop | None:
        if self.cloud_client is None or not SLUG_PATTERN.match(slug):
            return None
        try:
            row = await self.cloud_client.get_sop(slug)
        except DataCloudError:
            return None
        return self._from_row(row)

    async def _save_cloud(self, slug: str, content: str) -> Sop:
        client = self.cloud_client
        if client is None:
            raise ValueError('no data cloud client')
        try:
            row = await client.update_sop(slug, {'content': content})
        except DataCloudError as error:
            if error.status_code != 404:
                raise
            row = await client.create_sop({'slug': slug, 'content': content})
        sop = self._from_row(row)
        if sop is None:
            raise ValueError(f'data cloud returned no sop for {slug}')
        return sop

    async def _delete_cloud(self, slug: str) -> bool:
        client = self.cloud_client
        if client is None:
            return False
        try:
            await client.delete_sop(slug)
        except DataCloudError as error:
            if error.status_code == 404:
                return False
            raise
        return True

    @staticmethod
    def _from_row(row: dict) -> Sop | None:
        slug = str(row.get('slug') or '')
        if not slug:
            return None
        content = str(row.get('content') or '')
        return Sop(slug, str(row.get('title') or title_of(content, slug)), content, CLOUD_SOURCE)


def validate(slug: str, content: str) -> None:
    if not SLUG_PATTERN.match(slug):
        raise ValueError(SLUG_PATTERN_HINT)
    if not content.strip():
        raise ValueError('content is required')
    if len(content) > MAX_CONTENT:
        raise ValueError(f'content must be at most {MAX_CONTENT} characters')
