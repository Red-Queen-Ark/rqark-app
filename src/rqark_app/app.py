import asyncio
import logging
import os
from typing import Any

from openai import APIError
from rqark_core.core import AgentCore
from rqark_core.types.chat import Message, UserMessage
from rqark_core.types.event import AgentPayload
from rqark_core.types.provider import Provider
from rqark_core.types.tool import PlanItem

from rqark_app._app.core import create_core
from rqark_app._app.event import AgentAppEventEmitter
from rqark_app._app.helper import ChatHelper
from rqark_app.cloud.client import DataCloudError, RQArkDataCloudClient
from rqark_app.compact import Compactor, is_context_overflow
from rqark_app.memory import DEFAULT_USER_NAME, USER_NAME_KEY, TurnMemoryWriter, load_memory_settings, turn_from_session, user_name_from_prompts
from rqark_app.prompts.memory import PROMPT_KEY
from rqark_app.provider.manager import ProviderManager
from rqark_app.session.manager import SessionManager
from rqark_app.session.storage import CloudStorage, SessionStorage
from rqark_app.tools.context import AGENT_KEY, CLIENT_KEY
from rqark_app.types.agent import BaseAgent
from rqark_app.types.session import Session

logger = logging.getLogger(__name__)

TURN_MEMORY_TIMEOUT = 15.0
TURN_MEMORY_DRAIN_TIMEOUT = 5.0
_DERIVE_CLOUD_CLIENT = object()


def _auto_write_default() -> bool:
    """Whether turns are recorded automatically, from RQARK_MEMORY_AUTO_WRITE.

    On by default: the whole point of the writer is that nobody has to remember
    to call memory_save. 0, false, no and off switch it off.
    """
    raw = os.environ.get('RQARK_MEMORY_AUTO_WRITE', '').strip().lower()
    return raw not in {'0', 'false', 'no', 'off'}


def _resolve_cloud_client(storage: SessionStorage | None, cloud_client: RQArkDataCloudClient | None | object) -> RQArkDataCloudClient | None:
    """The client a turn proxies through: given one when the caller decided, otherwise the storage's own.

    Passing None explicitly is how a caller keeps the provider's own key: a task
    run holds a run-scoped token, which the data cloud does not accept for model
    calls, so it cannot use the proxy even though it stores in the cloud.
    """
    if isinstance(cloud_client, RQArkDataCloudClient):
        return cloud_client
    if cloud_client is not _DERIVE_CLOUD_CLIENT:
        return None
    if isinstance(storage, CloudStorage):
        return storage.client
    return None


class AgentApp(AgentAppEventEmitter):
    def __init__(self, providers: list[Provider], storage: SessionStorage | None = None, cloud_client: RQArkDataCloudClient | None | object = _DERIVE_CLOUD_CLIENT):
        super().__init__()
        self.cloud_client: RQArkDataCloudClient | None = _resolve_cloud_client(storage, cloud_client)
        self.provider_mgr = ProviderManager(providers)
        self.session_mgr = SessionManager(storage)
        self.chat_helper = ChatHelper(self.provider_mgr, self.session_mgr, self._emit, self.cloud_client)
        self.compactor = Compactor(self.provider_mgr)
        self.auto_write_memory = _auto_write_default()
        self._memory_writes: set[asyncio.Task] = set()

    def _connect_event(self, core: AgentCore):
        core.on_chunk()(self.handle_chunk_event)
        core.on_message()(self.handle_message_event)
        core.on_plan()(self.handle_plan)
        core.on_plan()(self.handle_save_plan)

    async def handle_save_plan(self, ev: AgentPayload[list[PlanItem]]):
        session = await self.session_mgr.set_plan(ev.agent_id, ev.payload)
        if session is not None:
            await self.session_mgr.save(session.uuid)

    async def chat(self, content: str, agent: BaseAgent, session_id: str | None = None, path: tuple[str, ...] = (), images: list[str] | None = None, extras: dict[str, Any] | None = None) -> Session:
        session = await self.session_mgr.get_or_create(session_id) if session_id else await self.session_mgr.create()
        if extras is not None:
            # The memory writer runs its own core, without this agent's role prompt,
            # so the name the turn addresses the human by is carried over in extras.
            extras[USER_NAME_KEY] = user_name_from_prompts(agent.prompts)
        core = create_core(f'{agent.name}:{session.uuid}', self.cloud_client, path=path, extras=extras)
        # A core is created per turn, so the plan stored on the session must be seeded back
        # or plan_update would render "No active plan" for every turn of an ongoing plan.
        core.plan_items = [PlanItem(p.id, p.content, p.status) for p in session.plan_items]
        user_msg = UserMessage(content, images=list(images) if images else [])
        await self._emit('message', AgentPayload(core.agent_id, core.path, user_msg))
        self._connect_event(core)
        history = [*session.get_last_chunk_for_chat(), user_msg]
        return await self._loop(session, core, agent, history)

    async def write_turn_memory(self, *, session_id: str, source: str, session: Session, extras: dict[str, Any] | None = None, allow_state_update: bool = True) -> None:
        """Record one finished turn in the background: one event, the new state.

        The caller runs this in a task after the turn has been answered, so it
        must never make the answer wait and must never raise (a cancellation is
        the one exception: the shutdown path has to be able to stop it).

        extras is the same dict the turn ran with, so the data cloud pair and the
        state the prompt already read are reused instead of asked for twice. A
        turn with no cloud client or no agent id is a no-op.

        What gets written is the account's call: two switches in the user config
        (memory.event_log and memory.state_update) can turn either half off, and
        they are read here so a flip in the web UI applies to the next turn.
        memory.event_log stops both rows this writer leaves (the event and the
        occasional fact) but not a fact the agent saves itself; both off also
        means no model call and no state read.
        """
        if not self.auto_write_memory:
            return
        extras = extras or {}
        client = extras.get(CLIENT_KEY)
        agent_id = extras.get(AGENT_KEY)
        if client is None or not agent_id:
            return

        settings = await load_memory_settings(client)
        if not settings.event_log and not settings.state_update:
            return

        task = asyncio.current_task()
        if task is not None:
            self._memory_writes.add(task)
        try:
            async with asyncio.timeout(TURN_MEMORY_TIMEOUT):
                current_state = await self._current_state(client, str(agent_id), extras) if settings.state_update else None
                user_text, assistant_text, tool_calls = turn_from_session(session)
                user_name = extras.get(USER_NAME_KEY)
                writer = TurnMemoryWriter(self.provider_mgr, client, cloud_client=self.cloud_client)
                await writer.write(
                    agent_id=str(agent_id),
                    source=source,
                    user_text=user_text,
                    assistant_text=assistant_text,
                    tool_calls=tool_calls,
                    session_id=session_id,
                    current_state=current_state,
                    allow_state_update=allow_state_update and settings.state_update,
                    write_log=settings.event_log,
                    user_name=user_name if isinstance(user_name, str) and user_name.strip() else DEFAULT_USER_NAME,
                )
        except TimeoutError:
            logger.warning('memory writer timed out session=%s', session_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception('memory writer failed session=%s', session_id)
        finally:
            if task is not None:
                self._memory_writes.discard(task)

    async def _current_state(self, client: RQArkDataCloudClient, agent_id: str, extras: dict[str, Any]) -> dict | None:
        """The state as it stood when this turn started.

        The prompt already fetched it once this turn; reusing that copy is also
        what makes the optimistic lock honest, because the version sent back is
        the one the turn actually saw.
        """
        cached = extras.get(PROMPT_KEY)
        if isinstance(cached, dict):
            state = cached.get('state')
            return state if isinstance(state, dict) else None
        try:
            return await client.get_state(agent_id)
        except DataCloudError as error:
            logger.warning('memory writer could not read the state error=%s', error)
            return None

    async def drain_memory_writes(self, timeout: float = TURN_MEMORY_DRAIN_TIMEOUT) -> None:
        """Wait for the writes still running, up to timeout.

        Called on shutdown: a task nobody awaits is dropped when the loop closes,
        which would lose the memory of the last turn exactly when it matters.
        """
        pending = [task for task in self._memory_writes if not task.done()]
        if not pending:
            return
        logger.info('waiting for %d pending memory writes', len(pending))
        try:
            async with asyncio.timeout(timeout):
                await asyncio.gather(*pending, return_exceptions=True)
        except TimeoutError:
            logger.warning('gave up waiting for memory writes after %.1fs', timeout)

    async def _loop(self, session: Session, core: AgentCore, agent: BaseAgent, history: list[Message]) -> Session:
        while True:
            provider = self.provider_mgr.provider
            new_messages, error = await core.chat(provider, history, agent.prompts, agent.tools)
            history = list(new_messages)
            session.update_history_to_last_chunk(history)
            await self.session_mgr.save(session.uuid)
            if error is None:
                return session
            if is_context_overflow(error):
                summary = await self.compactor.get_summary(session.get_last_chunk_for_chat(), self.cloud_client)
                if summary:
                    session.history += [summary]
                    await self.session_mgr.save(session.uuid)
                    history = session.get_last_chunk_for_chat()
                    continue
            if not isinstance(error, APIError):
                raise error
            await self.chat_helper.report_failure(core, provider)
