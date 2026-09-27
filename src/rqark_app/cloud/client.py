from types import TracebackType

import httpx

from rqark_app.types.cloud import CloudConfig


class DataCloudError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


class RQArkDataCloudClient:
    def __init__(self, config: CloudConfig, timeout: float = 30.0, transport: httpx.AsyncBaseTransport | None = None):
        self.config = config
        self.timeout = timeout
        self._client = httpx.AsyncClient(timeout=self.timeout, transport=transport)

    @property
    def api_url(self) -> str:
        url = self.config.url.rstrip('/')
        if url.endswith('/api'):
            return url
        return f'{url}/api'

    async def request(self, method: str, path: str, **kwargs) -> httpx.Response:
        if not self.config.configured:
            raise DataCloudError(0, 'NOT_CONFIGURED', 'data cloud is not enabled, or has no url and api key')
        url = self._url(path)
        try:
            response = await self._client.request(method, url, headers=self._headers(), **kwargs)
        except httpx.HTTPError as error:
            raise DataCloudError(0, 'REQUEST_FAILED', f'cannot reach data cloud at {url}: {error}') from error
        if response.status_code >= 400:
            raise self._error(response)
        return response

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> RQArkDataCloudClient:
        return self

    async def __aexit__(self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None) -> None:
        await self.aclose()

    async def me(self) -> dict:
        return self._json(await self.request('GET', 'users/me')) or {}

    async def list_agents(self, limit: int | None = None, offset: int | None = None) -> list[dict]:
        return await self._list('agents', limit, offset)

    async def get_agent(self, uuid: str) -> dict:
        return self._json(await self.request('GET', f'agents/{uuid}')) or {}

    async def create_agent(self, payload: dict) -> dict:
        return self._json(await self.request('POST', 'agents', json=payload)) or {}

    async def update_agent(self, uuid: str, payload: dict) -> dict:
        return self._json(await self.request('PUT', f'agents/{uuid}', json=payload)) or {}

    async def delete_agent(self, uuid: str) -> None:
        await self.request('DELETE', f'agents/{uuid}')

    async def list_providers(self, limit: int | None = None, offset: int | None = None) -> list[dict]:
        return await self._list('providers', limit, offset)

    async def get_provider(self, uuid: str) -> dict:
        return self._json(await self.request('GET', f'providers/{uuid}')) or {}

    async def create_provider(self, payload: dict) -> dict:
        return self._json(await self.request('POST', 'providers', json=payload)) or {}

    async def update_provider(self, uuid: str, payload: dict) -> dict:
        return self._json(await self.request('PUT', f'providers/{uuid}', json=payload)) or {}

    async def delete_provider(self, uuid: str) -> None:
        await self.request('DELETE', f'providers/{uuid}')

    async def list_sessions(self, limit: int | None = None, offset: int | None = None) -> list[dict]:
        return await self._list('sessions', limit, offset)

    async def get_session(self, uuid: str) -> dict:
        return self._json(await self.request('GET', f'sessions/{uuid}')) or {}

    async def create_session(self, payload: dict) -> dict:
        return self._json(await self.request('POST', 'sessions', json=payload)) or {}

    async def update_session(self, uuid: str, payload: dict) -> dict:
        return self._json(await self.request('PUT', f'sessions/{uuid}', json=payload)) or {}

    async def delete_session(self, uuid: str) -> None:
        await self.request('DELETE', f'sessions/{uuid}')

    async def list_session_messages(self, uuid: str, limit: int | None = None, offset: int | None = None) -> list[dict]:
        return await self._list(f'sessions/{uuid}/messages', limit, offset)

    def _headers(self) -> dict[str, str]:
        return {'Authorization': f'Bearer {self.config.api_key}'}

    def _url(self, path: str) -> str:
        return f'{self.api_url}/{path.lstrip("/")}'

    async def _list(self, path: str, limit: int | None, offset: int | None) -> list[dict]:
        items = self._json(await self.request('GET', path)) or []
        start = offset or 0
        if limit is None:
            return items[start:]
        return items[start : start + limit]

    def _json(self, response: httpx.Response):
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError as error:
            raise DataCloudError(response.status_code, 'INVALID_RESPONSE', f'data cloud answered {response.status_code} with a body that is not json') from error

    def _error(self, response: httpx.Response) -> DataCloudError:
        code = 'UNKNOWN'
        message = f'data cloud answered {response.status_code}'
        try:
            error = response.json().get('error') or {}
        except ValueError:
            error = {}
        code = str(error.get('code') or code)
        message = str(error.get('message') or message)
        return DataCloudError(response.status_code, code, message)
