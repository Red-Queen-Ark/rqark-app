import json
import logging
from datetime import UTC, datetime
from typing import Any

from rqark_core.types.chat import AssistantMessage, ToolMessage, UserMessage

from rqark_app._app.core import create_core
from rqark_app.cloud.client import DataCloudError, RQArkDataCloudClient
from rqark_app.prompts.memory_writer import DEFAULT_USER_NAME, MemoryWritePrompt
from rqark_app.provider.manager import ProviderManager
from rqark_app.types.session import Session

logger = logging.getLogger(__name__)

MAX_STATE_CHARS = 2000
MAX_EVENT_CHARS = 200
SHORT_REPLY_CHARS = 200
TOOL_NOTE_CHARS = 200
USER_NAME_KEY = 'user_name'


def user_name_from_prompts(prompts: Any) -> str:
    """The human's name, taken from the role prompt the agent already carries.

    A prompt that names its user (RolePrompt, or anything shaped like it) wins;
    otherwise the writer falls back to DEFAULT_USER_NAME rather than guess a
    persona the turn never had.
    """
    for prompt in prompts or ():
        name = getattr(prompt, 'user_name', None)
        if isinstance(name, str) and name.strip():
            return name.strip()
    return DEFAULT_USER_NAME


class TurnMemoryWriter:
    """Records one finished turn: one event, sometimes a fact, and the new state.

    The event and the fact are the writer's own logging of the turn and are
    turned off together by the account's memory.event_log switch; a fact the
    agent saved itself through memory_save is a different thing and stays.

    The writer never raises for a cloud failure: memory is a background
    enrichment, and a turn that has already been answered must not fail because
    the log could not be extended.
    """

    def __init__(self, provider_mgr: ProviderManager, client: RQArkDataCloudClient, cloud_client: RQArkDataCloudClient | None = None):
        self.provider_mgr = provider_mgr
        self.client = client
        self.cloud_client = cloud_client

    async def write(self, *, agent_id: str, source: str, user_text: str, assistant_text: str, tool_calls: list[str], session_id: str, current_state: dict | None, allow_state_update: bool = True, write_log: bool = True, user_name: str = DEFAULT_USER_NAME) -> None:
        if should_skip(user_text, assistant_text, tool_calls):
            return

        answer = await self._ask(user_text, assistant_text, tool_calls, session_id, current_state, user_name)
        if not answer:
            return
        if answer.get('skip') is True:
            logger.info('memory writer skipped the turn session=%s', session_id)
            return

        if allow_state_update:
            await self._write_state(agent_id, source, session_id, current_state, answer.get('state'))
        if write_log:
            await self._write_rows(agent_id, source, session_id, answer.get('events'), kind='event')
            await self._write_rows(agent_id, source, session_id, answer.get('facts'), kind='fact')

    async def _ask(self, user_text: str, assistant_text: str, tool_calls: list[str], session_id: str, current_state: dict | None, user_name: str) -> dict:
        """One model call: the state as it stands plus the turn, into JSON."""
        request = {'current_state': (current_state or {}).get('content') or '', 'user_message': user_text, 'assistant_reply': assistant_text, 'tool_calls': tool_calls}
        core = create_core('Memory', self.cloud_client)
        messages, error = await core.chat(self.provider_mgr.provider, [UserMessage(json.dumps(request, ensure_ascii=False))], [MemoryWritePrompt(user_name)], [])
        if error is not None:
            logger.warning('memory writer model call failed session=%s error=%s', session_id, error)
            return {}
        if not messages:
            return {}
        return parse_answer(messages[-1].content)

    async def _write_state(self, agent_id: str, source: str, session_id: str, current_state: dict | None, state: Any) -> None:
        if not isinstance(state, str):
            return
        content = state.strip()
        if not content:
            return
        if len(content) > MAX_STATE_CHARS:
            logger.warning('memory writer produced a %d character state, keeping the old one session=%s', len(content), session_id)
            return

        version = current_state.get('version') if isinstance(current_state, dict) else None
        try:
            await self.client.set_state(agent_id, content, source, version=version if isinstance(version, int) else None)
            return
        except DataCloudError as error:
            if error.code != 'STATE_CONFLICT':
                logger.warning('memory writer could not store the state session=%s error=%s', session_id, error)
                return

        fresh = await self._fresh_version(agent_id, session_id)
        if fresh is None:
            return
        try:
            await self.client.set_state(agent_id, content, source, version=fresh)
        except DataCloudError as error:
            logger.warning('memory writer could not store the state after a conflict session=%s error=%s', session_id, error)

    async def _fresh_version(self, agent_id: str, session_id: str) -> int | None:
        try:
            state = await self.client.get_state(agent_id)
        except DataCloudError as error:
            logger.warning('memory writer could not re-read the state session=%s error=%s', session_id, error)
            return None
        version = (state or {}).get('version')
        return version if isinstance(version, int) else None

    async def _write_rows(self, agent_id: str, source: str, session_id: str, rows: Any, *, kind: str) -> None:
        for content, keywords in row_entries(rows, kind=kind):
            payload: dict[str, Any] = {'agent_id': agent_id, 'content': content, 'kind': kind, 'source': source, 'occurred_at': datetime.now(UTC).isoformat()}
            if keywords:
                payload['keywords'] = keywords
            try:
                await self.client.create_memory(payload)
            except DataCloudError as error:
                logger.warning('memory writer could not store a %s session=%s error=%s', kind, session_id, error)


def should_skip(user_text: str, assistant_text: str, tool_calls: list[str]) -> bool:
    """True for a turn that is not worth a model call at all.

    A turn that called a tool did something and is always considered; a turn
    without one is only considered when the answer is substantial, so "喂" or a
    one-line reply never costs a call or leaves a row.
    """
    if not user_text.strip():
        return True
    if tool_calls:
        return False
    return len(assistant_text.strip()) < SHORT_REPLY_CHARS


def parse_answer(text: str) -> dict:
    """Read the writer's JSON object, tolerating a fenced code block.

    A reply that is not a JSON object is reported as an empty answer: the turn
    has already been answered, so there is nothing to retry against.
    """
    body = text.strip()
    if body.startswith('```'):
        body = body.split('\n', 1)[-1]
        if body.rstrip().endswith('```'):
            body = body.rstrip()[:-3]
    start = body.find('{')
    end = body.rfind('}')
    if start == -1 or end <= start:
        return {}
    try:
        parsed = json.loads(body[start : end + 1])
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def row_entries(rows: Any, *, kind: str) -> list[tuple[str, list[str]]]:
    """Normalise the events or facts of an answer into storable rows.

    An entry with no content is dropped rather than stored empty, and one that
    is too long is clamped: the data cloud caps a row at 200 characters, and
    losing the tail of a note is better than losing the note.
    """
    if not isinstance(rows, list):
        return []
    entries: list[tuple[str, list[str]]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        content = row.get('content')
        if not isinstance(content, str) or not content.strip():
            continue
        clamped = content.strip()[:MAX_EVENT_CHARS]
        if len(clamped) < len(content.strip()):
            logger.warning('memory writer clamped a %s from %d to %d characters', kind, len(content.strip()), MAX_EVENT_CHARS)
        keywords = row.get('keywords')
        cleaned = [str(keyword).strip() for keyword in keywords if str(keyword).strip()] if isinstance(keywords, list) else []
        entries.append((clamped, cleaned[:8]))
    return entries


def turn_from_session(session: Session) -> tuple[str, str, list[str]]:
    """The user text, the final reply and the tool notes of the last turn.

    The last user message starts the turn; everything after it belongs to the
    answer. Tool notes carry the call name and a one-line cut of its arguments:
    enough for the writer to say what was done, never the raw result, which can
    be megabytes of file content.
    """
    messages = session.get_last_chunk()
    user_text = ''
    start = 0
    for index, message in enumerate(messages):
        if isinstance(message, UserMessage):
            user_text = message.content
            start = index + 1

    assistant_text = ''
    notes: list[str] = []
    for message in messages[start:]:
        if isinstance(message, AssistantMessage):
            if message.content.strip():
                assistant_text = message.content
            for call in message.tool_calls or []:
                notes.append(tool_note(call.name, call.arguments))
        elif isinstance(message, ToolMessage) and not notes:
            notes.append(tool_note(message.tool_name or 'tool', ''))
    return user_text, assistant_text, notes


def tool_note(name: str, arguments: str) -> str:
    """One line describing a tool call: its name and a cut of its arguments."""
    collapsed = ' '.join(str(arguments).split())
    if not collapsed:
        return name
    if len(collapsed) > TOOL_NOTE_CHARS:
        collapsed = collapsed[:TOOL_NOTE_CHARS] + '…'
    return f'{name} {collapsed}'
