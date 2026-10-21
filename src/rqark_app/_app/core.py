from rqark_core.core import AgentCore

from rqark_app.cloud.chat import CloudAgentCore
from rqark_app.cloud.client import RQArkDataCloudClient


def create_core(name: str, cloud_client: RQArkDataCloudClient | None = None, path: tuple[str, ...] = (), extras: dict | None = None) -> AgentCore:
    """Build the core a turn runs on: through the data cloud when one is configured.

    A cloud client means the providers came from the data cloud and their keys
    stayed there, so the calls have to be proxied; without one the providers
    carry their own key and the core talks to them directly.
    """
    if cloud_client is None:
        return AgentCore(name, path=path, extras=extras)
    return CloudAgentCore(cloud_client, name, path=path, extras=extras)


def cloud_client_of(core: AgentCore) -> RQArkDataCloudClient | None:
    """The data cloud client a core proxies through, or None when it talks to providers directly."""
    return getattr(core, 'cloud_client', None)
