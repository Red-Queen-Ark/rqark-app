import re
from dataclasses import dataclass

MAX_CONTENT = 2000
MAX_TITLE = 255

LOCAL_SOURCE = 'local'
CLOUD_SOURCE = 'cloud'

SLUG_PATTERN = re.compile(r'^[a-z0-9][a-z0-9-]{0,63}$')
SLUG_PATTERN_HINT = 'slug must be 1 to 64 characters of lowercase letters, digits and hyphens, and must not start with a hyphen'


@dataclass
class Sop:
    slug: str
    title: str
    content: str
    source: str

    @property
    def local(self) -> bool:
        return self.source == LOCAL_SOURCE


def title_of(content: str, slug: str) -> str:
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith('#'):
            return line.lstrip('#').strip()[:MAX_TITLE] or slug
        break
    return slug
