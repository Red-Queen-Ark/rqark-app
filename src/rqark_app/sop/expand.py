from collections.abc import Sequence

from rqark_app.sop.types import Sop


def parse(command: str) -> tuple[str, str] | None:
    text = command.strip()
    if not text.startswith('/'):
        return None
    head, _, args = text[1:].partition(' ')
    slug = head.strip()
    if not slug:
        return None
    return slug, args.strip()


def expand(command: str, sops: Sequence[Sop]) -> tuple[str, str] | None:
    parsed = parse(command)
    if parsed is None:
        return None
    slug, args = parsed
    sop = next((sop for sop in sops if sop.slug == slug), None)
    if sop is None:
        return None
    head = f'#{slug} {args}'.rstrip()
    return f'{head}\n\n{sop.content}', slug
