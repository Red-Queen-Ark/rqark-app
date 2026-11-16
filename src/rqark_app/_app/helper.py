import asyncio
from collections.abc import Awaitable, Callable

from rqark_core.core import AgentCore
from rqark_core.types.chat import UserMessage
from rqark_core.types.event import AgentPayload
from rqark_core.types.provider import Provider

from rqark_app._app.core import create_core
from rqark_app.cloud.client import RQArkDataCloudClient
from rqark_app.prompts.title import GentTilte
from rqark_app.provider.manager import ProviderManager
from rqark_app.session.manager import SessionManager
from rqark_app.tools.context import SESSION_KEY, SOURCE_KEY
from rqark_app.types.event import ProviderSwitch
from rqark_app.types.session import Session


class ChatHelper:
    def __init__(self, provider_mgr: ProviderManager, session_mgr: SessionManager, emit: Callable[..., Awaitable[None]], cloud_client: RQArkDataCloudClient | None = None):
        self.provider_mgr = provider_mgr
        self.session_mgr = session_mgr
        self._emit = emit
        self.cloud_client = cloud_client

    async def report_failure(self, core: AgentCore, provider: Provider):
        self.provider_mgr.report_failure()
        if self.provider_mgr.provider is not provider:
            await self._emit('provider_switched', AgentPayload(core.agent_id, core.path, ProviderSwitch(old=provider, new=self.provider_mgr.provider)))
        await asyncio.sleep(1)

    def _usage_tags(self, session_id: str) -> dict[str, str]:
        tags = {SESSION_KEY: session_id}
        source = getattr(self.session_mgr.storage, 'source', '')
        if source:
            tags[SOURCE_KEY] = str(source)
        return tags

    async def gen_title(self, session_id: str, content: str) -> Session | None:
        session = await self.session_mgr.get(session_id)
        if session is None:
            return None
        core = create_core('GenTitle', self.cloud_client, extras=self._usage_tags(session_id))
        provider = self.provider_mgr.provider
        for _ in range(3):
            new_messages, error = await core.chat(provider, [UserMessage(content)], [GentTilte()], [])
            if error is None:
                session.title = new_messages[-1].content
                await self.session_mgr.save(session.uuid)
            else:
                await self.report_failure(core, provider)
        return session
