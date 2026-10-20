import logging
from dataclasses import dataclass

from rqark_app.cloud.client import DataCloudError, RQArkDataCloudClient

logger = logging.getLogger(__name__)

EVENT_LOG_KEY = 'memory.event_log'
STATE_UPDATE_KEY = 'memory.state_update'


@dataclass(frozen=True)
class MemorySettings:
    """What a finished turn is allowed to write; both on unless the account said otherwise."""

    event_log: bool = True
    state_update: bool = True


async def load_memory_settings(client: RQArkDataCloudClient) -> MemorySettings:
    """The account's switches, read before every turn.

    Reading it per turn rather than caching it at startup is what lets a flip
    in the web UI take effect on the next turn instead of after a restart; it
    is one small request next to the model call the writer is about to make.

    A read that fails leaves both switches on: the log of a turn is worth more
    than the rare row written for somebody who had just turned it off.
    """
    try:
        entries = await client.list_user_config()
    except DataCloudError as error:
        logger.warning('could not read the memory settings error=%s', error)
        return MemorySettings()

    values = {entry.get('key'): entry.get('value') for entry in entries if isinstance(entry, dict)}
    return MemorySettings(event_log=_enabled(values.get(EVENT_LOG_KEY)), state_update=_enabled(values.get(STATE_UPDATE_KEY)))


def _enabled(value: object) -> bool:
    """Only a stored false turns a switch off; a missing key means on."""
    return value is not False
