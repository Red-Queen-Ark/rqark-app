from collections.abc import Sequence

from rqark_app._app.core import create_core
from rqark_app.cloud.client import RQArkDataCloudClient
from rqark_app.compact.messages import compact_messages, trim_tail
from rqark_app.compact.prompt import CompactContext
from rqark_app.provider.manager import ProviderManager
from rqark_app.types.session import HistoryMessage, SummaryMessage


class Compactor:
    def __init__(self, provider_mgr: ProviderManager):
        self.provider_mgr = provider_mgr

    async def get_summary(self, messages: Sequence[HistoryMessage], cloud_client: RQArkDataCloudClient | None = None) -> SummaryMessage | None:
        trimmed = compact_messages(messages)
        if not trimmed:
            return None
        core = create_core('Compact', cloud_client)
        provider = self.provider_mgr.provider
        while trimmed:
            new_messages, error = await core.chat(provider, trimmed, [CompactContext()], [])
            if error is None and new_messages:
                return SummaryMessage(new_messages[-1].content)
            shrunk = trim_tail(trimmed)
            if shrunk is None:
                break
            trimmed = shrunk
        return None
