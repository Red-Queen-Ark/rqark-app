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

    async def list_sessions(self, source: str | None = None, limit: int | None = None, offset: int | None = None) -> list[dict]:
        params = {'source': source} if source is not None else None
        return await self._list('sessions', limit, offset, params)

    async def get_session(self, uuid: str) -> dict:
        return self._json(await self.request('GET', f'sessions/{uuid}')) or {}

    async def create_session(self, payload: dict, source: str | None = None) -> dict:
        return self._json(await self.request('POST', 'sessions', json=self._with_source(payload, source))) or {}

    async def update_session(self, uuid: str, payload: dict, source: str | None = None) -> dict:
        return self._json(await self.request('PUT', f'sessions/{uuid}', json=self._with_source(payload, source))) or {}

    async def delete_session(self, uuid: str) -> None:
        await self.request('DELETE', f'sessions/{uuid}')

    async def list_session_messages(self, uuid: str, limit: int | None = None, offset: int | None = None) -> list[dict]:
        return await self._list(f'sessions/{uuid}/messages', limit, offset)

    async def list_memory(self, agent_id: str | None = None, cursor: str | None = None, limit: int | None = None) -> dict:
        params: dict[str, str] = {}
        if agent_id is not None:
            params['agent_id'] = agent_id
        if cursor:
            params['cursor'] = cursor
        if limit is not None:
            params['limit'] = str(limit)
        return self._json(await self.request('GET', 'memory', params=params or None)) or {}

    async def get_memory(self, uuid: str) -> dict:
        return self._json(await self.request('GET', f'memory/{uuid}')) or {}

    async def create_memory(self, payload: dict) -> dict:
        return self._json(await self.request('POST', 'memory', json=payload)) or {}

    async def set_memory_pinned(self, uuid: str, pinned: bool) -> dict:
        return self._json(await self.request('PATCH', f'memory/{uuid}', json={'pinned': pinned})) or {}

    async def delete_memory(self, uuid: str) -> None:
        await self.request('DELETE', f'memory/{uuid}')

    async def search_memory(self, agent_id: str, query: str | None = None, keywords: list[str] | None = None, at: str | None = None) -> list[dict]:
        payload: dict = {'agent_id': agent_id}
        if query:
            payload['query'] = query
        if keywords:
            payload['keywords'] = keywords
        if at:
            payload['at'] = at
        return self._json(await self.request('POST', 'memory/search', json=payload)) or []

    async def prompt_memory(self, agent_id: str) -> list[dict]:
        return self._json(await self.request('POST', 'memory/prompt', json={'agent_id': agent_id})) or []

    async def list_sops(self) -> list[dict]:
        sops: list[dict] = []
        cursor = ''
        while True:
            page = self._json(await self.request('GET', 'sops', params={'cursor': cursor} if cursor else None)) or {}
            sops.extend(page.get('items') or [])
            cursor = str(page.get('next_cursor') or '')
            if not cursor:
                return sops

    async def get_sop(self, slug: str) -> dict:
        return self._json(await self.request('GET', f'sops/{slug}')) or {}

    async def create_sop(self, payload: dict) -> dict:
        return self._json(await self.request('POST', 'sops', json=payload)) or {}

    async def update_sop(self, slug: str, payload: dict) -> dict:
        return self._json(await self.request('PATCH', f'sops/{slug}', json=payload)) or {}

    async def delete_sop(self, slug: str) -> None:
        await self.request('DELETE', f'sops/{slug}')

    async def list_tasks(self) -> list[dict]:
        return self._json(await self.request('GET', 'tasks')) or []

    async def get_task(self, uuid: str) -> dict:
        return self._json(await self.request('GET', f'tasks/{uuid}')) or {}

    async def create_task(self, payload: dict) -> dict:
        return self._json(await self.request('POST', 'tasks', json=payload)) or {}

    async def update_task(self, uuid: str, payload: dict) -> dict:
        return self._json(await self.request('PUT', f'tasks/{uuid}', json=payload)) or {}

    async def delete_task(self, uuid: str) -> None:
        await self.request('DELETE', f'tasks/{uuid}')

    async def run_task(self, uuid: str) -> dict:
        return self._json(await self.request('POST', f'tasks/{uuid}/run')) or {}

    async def list_task_runs(self, uuid: str, limit: int | None = None, offset: int | None = None) -> dict:
        params: dict[str, str] = {}
        if limit is not None:
            params['limit'] = str(limit)
        if offset is not None:
            params['offset'] = str(offset)
        return self._json(await self.request('GET', f'tasks/{uuid}/runs', params=params or None)) or {}

    async def list_agent_defaults(self) -> list[dict]:
        return await self._list('agent-defaults', None, None)

    async def get_agent_default(self, source: str) -> dict | None:
        try:
            return self._json(await self.request('GET', f'agent-defaults/{source}')) or {}
        except DataCloudError as error:
            if error.status_code == 404:
                return None
            raise

    async def set_agent_default(self, source: str, agent_id: str) -> dict:
        return self._json(await self.request('PUT', f'agent-defaults/{source}', json={'agent_id': agent_id})) or {}

    async def delete_agent_default(self, source: str) -> bool:
        try:
            await self.request('DELETE', f'agent-defaults/{source}')
        except DataCloudError as error:
            if error.status_code == 404:
                return False
            raise
        return True

    def _headers(self) -> dict[str, str]:
        return {'Authorization': f'Bearer {self.config.api_key}'}

    def _url(self, path: str) -> str:
        return f'{self.api_url}/{path.lstrip("/")}'

    @staticmethod
    def _with_source(payload: dict, source: str | None) -> dict:
        if source is None:
            return payload
        return {**payload, 'source': source}

    async def _list(self, path: str, limit: int | None, offset: int | None, params: dict | None = None) -> list[dict]:
        items = self._json(await self.request('GET', path, params=params)) or []
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
            body = response.json()
        except ValueError:
            body = {}
        error = body.get('error') if isinstance(body, dict) else None
        if not isinstance(error, dict):
            error = {}
        code = str(error.get('code') or code)
        message = str(error.get('message') or message)
        return DataCloudError(response.status_code, code, message)
