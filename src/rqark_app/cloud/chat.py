import ssl
from typing import Any

import certifi
import httpx2
from openai import AsyncOpenAI
from rqark_core.core import AgentCore
from rqark_core.types.provider import Provider

from rqark_app.cloud.client import RQArkDataCloudClient


class RefreshingAuth(httpx2.Auth):
    """Repeats a refused request once, after the data cloud client has refreshed its token.

    The token is read off the client on every attempt rather than captured here,
    so a fresh one is picked up without rebuilding the HTTP client. A second 401
    is passed on: if a new token is also refused, retrying again would not help.
    """

    def __init__(self, client: RQArkDataCloudClient):
        self.client = client

    async def async_auth_flow(self, request: httpx2.Request):
        request.headers['Authorization'] = f'Bearer {self.client.config.api_key}'
        response = yield request
        if response.status_code != 401 or self.client.on_unauthorized is None:
            return
        await self.client.on_unauthorized()
        request.headers['Authorization'] = f'Bearer {self.client.config.api_key}'
        yield request


class CloudAgentCore(AgentCore):
    """An AgentCore whose provider calls go through the data cloud.

    The provider is addressed by its id, so the caller never holds its key: the
    base URL names the provider and the api key is the data cloud token. The
    OpenAI SDK appends the chat path itself, which is why the proxy serves a
    provider as a base URL rather than as a field in the body.
    """

    def __init__(self, client: RQArkDataCloudClient, agent_id: str = '', path: tuple[str, ...] = (), timeout: float = 300, tool_timeout: float = 120, extras: dict[str, Any] | None = None):
        super().__init__(agent_id, path=path, timeout=timeout, tool_timeout=tool_timeout, extras=extras)
        self.cloud_client = client

    def _get_client(self, provider: Provider) -> AsyncOpenAI:
        if not provider.id:
            raise ValueError('cloud mode needs a provider id: this provider did not come from the data cloud')
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        http_client = httpx2.AsyncClient(verify=ssl_context, auth=RefreshingAuth(self.cloud_client))
        return AsyncOpenAI(api_key=self.cloud_client.config.api_key, base_url=f'{self.cloud_client.api_url}/chat/{provider.id}', http_client=http_client, default_headers={}, timeout=self.timeout)

    def _spawn(self, agent_id: str, path: tuple[str, ...], tool_timeout: float, extras: dict[str, Any]) -> AgentCore:
        """A subagent goes through the same proxy as its parent, so it keeps the client."""
        return CloudAgentCore(self.cloud_client, agent_id, path=path, timeout=self.timeout, tool_timeout=tool_timeout, extras=extras)
