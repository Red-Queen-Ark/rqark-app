import json
import logging
from typing import Any

from rqark_core.core import AgentCore
from rqark_core.types.chat import AssistantMessage, ToolMessage, UserMessage
from rqark_core.types.prompt import BasePrompt, PromptContext

from rqark_app.cloud.client import DataCloudError, RQArkDataCloudClient
from rqark_app.provider.manager import ProviderManager
from rqark_app.types.session import Session

logger = logging.getLogger(__name__)

MAX_STATE_CHARS = 2000
MAX_EVENT_CHARS = 200
SHORT_REPLY_CHARS = 200
TOOL_NOTE_CHARS = 200

_prompt = """
You maintain the memory of one user for one agent. You are given the current state board, the user's message, the assistant's final reply, and a summary of the tools the assistant called during the turn. Reply with ONE JSON object and nothing else.

{"skip": false,
 "state": "the complete updated markdown of the state board",
 "events": [{"content": "Boss asked for X; the agent did Y", "keywords": ["x", "y"]}],
 "facts": [{"content": "a durable fact about the user", "keywords": ["..."]}]}

The state board is what the next turn needs to know about right now: what is being worked on, what was just decided, what is still open. It is overwritten in full every turn, so write it as a complete brief, not a patch. Keep it under 2000 characters; compress older context rather than dropping the thread. Write it in the language of the conversation. Leave it unchanged when the turn changed nothing about the situation.

An event is one line recording what this turn asked and did, under 200 characters, in the conversation's language, written as "Boss asked for X; the agent did Y". Write one event for a turn that did something. These lines are never injected into the prompt; they are found by search when someone needs them.

A fact is a durable statement about the user that is still useful in another session: a preference, a decision, a deadline, an identity. Write a fact only when the user said something that will not expire with this conversation. Most turns have none, and a restated fact is not a new one.

Set "skip" to true and leave the other fields empty when the turn is small talk, a bare question with a short answer, an interruption, or a failure: there is nothing worth recording. Recording noise makes the log useless.
"""


class MemoryWritePrompt(BasePrompt):
    """The instructions of the background memory writer.

    Priority is irrelevant: the writer runs its own AgentCore with this prompt
    alone, never inside the user's turn.
    """

    priority: int = -1

    async def get_messages(self, ctx: PromptContext | None = None) -> str | None:
        return _prompt


class TurnMemoryWriter:
    """Records one finished turn: one event, sometimes a fact, and the new state.

    The writer never raises for a cloud failure: memory is a background
    enrichment, and a turn that has already been answered must not fail because
    the log could not be extended.
    """

    def __init__(self, provider_mgr: ProviderManager, client: RQArkDataCloudClient):
        self.provider_mgr = provider_mgr
        self.client = client

    async def write(self, *, agent_id: str, source: str, user_text: str, assistant_text: str, tool_calls: list[str], session_id: str, current_state: dict | None, allow_state_update: bool = True) -> None:
        if should_skip(user_text, assistant_text, tool_calls):
            return

        answer = await self._ask(user_text, assistant_text, tool_calls, session_id, current_state)
        if not answer:
            return
        if answer.get('skip') is True:
            logger.info('memory writer skipped the turn session=%s', session_id)
            return

        if allow_state_update:
            await self._write_state(agent_id, source, session_id, current_state, answer.get('state'))
        await self._write_rows(agent_id, source, session_id, answer.get('events'), kind='event')
        await self._write_rows(agent_id, source, session_id, answer.get('facts'), kind='fact')

    async def _ask(self, user_text: str, assistant_text: str, tool_calls: list[str], session_id: str, current_state: dict | None) -> dict:
        """One model call: the state as it stands plus the turn, into JSON."""
        request = {'current_state': (current_state or {}).get('content') or '', 'user_message': user_text, 'assistant_reply': assistant_text, 'tool_calls': tool_calls}
        core = AgentCore('Memory')
        messages, error = await core.chat(self.provider_mgr.provider, [UserMessage(json.dumps(request, ensure_ascii=False))], [MemoryWritePrompt()], [])
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
            payload: dict[str, Any] = {'agent_id': agent_id, 'content': content, 'kind': kind, 'source': source}
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
