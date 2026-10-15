import asyncio
import json
from pathlib import Path

import httpx
import pytest

from rqark_app.cloud.client import DataCloudError
from rqark_app.config.default import AGENTS, CLOUD
from rqark_app.config.manager import ConfigManager
from rqark_app.libs.io import IoHelper

CLOUD_YML = """
enabled: true
url: https://cloud.test
api_key: secret
"""

CLOUD_AGENT = {
    'id': '049e9b11-9729-4b97-92a5-16158df0ebfb',
    'name': 'CloudDiana',
    'description': 'from cloud',
    'prompts': [{'name': 'RolePrompt', 'params': {'agent_name': 'CloudDiana'}}],
    'tools': [],
    'created_at': '2026-09-25T17:05:24.181148Z',
    'updated_at': '2026-09-25T17:05:24.181148Z',
}

CLOUD_PROVIDER = {
    'id': '043d0a1d-3191-4d9c-b82c-3eee1a21629a',
    'name': 'cloud-p',
    'model_name': 'test-model',
    'api_key': 'test-key',
    'api_base': 'https://api.test',
    'priority': 2,
    'reasoning_effort': None,
    'thinking': 'disabled',
    'temperature': None,
    'top_p': None,
    'seed': None,
    'frequency_penalty': None,
    'presence_penalty': None,
    'combine': False,
    'created_at': '2026-09-25T13:02:02.66333Z',
    'updated_at': '2026-09-25T13:02:02.66333Z',
}

DIANA_YML = """
name: Diana
description: ''
prompts:
- name: RolePrompt
  params:
    agent_name: Diana
tools:
- name: Gitea
  params:
    username: diana
    token: secret-token
    base_url: https://gitea.example
- name: WebSearch
"""


def config_dir(tmp_path: Path) -> Path:
    (tmp_path / 'agents').mkdir(parents=True, exist_ok=True)
    return tmp_path


def load(tmp_path: Path) -> ConfigManager:
    config_mgr = ConfigManager(str(tmp_path))
    asyncio.run(config_mgr.load())
    return config_mgr


def test_a_tool_written_in_the_agent_file_reaches_the_agent(tmp_path: Path):
    (config_dir(tmp_path) / 'agents' / 'Diana.yml').write_text(DIANA_YML, encoding='utf-8')

    agents = load(tmp_path).agents

    assert [agent.name for agent in agents] == ['Diana']
    assert [tool.name for tool in agents[0].tools] == ['gitea', 'web_search']
    assert agents[0].tools[0].params() == {'token': 'secret-token', 'base_url': 'https://gitea.example', 'username': 'diana'}


def test_an_empty_agents_directory_is_seeded_with_the_presets(tmp_path: Path):
    config_mgr = load(tmp_path)

    assert [agent.name for agent in config_mgr.agents] == [agent.name for agent in AGENTS]
    assert sorted(p.name for p in (tmp_path / 'agents').iterdir()) == ['Angel_Holiday.yml', 'Diana.yml', 'Wednesday.yml']


def test_an_agents_directory_that_does_not_parse_falls_back_to_the_presets(tmp_path: Path):
    (config_dir(tmp_path) / 'agents' / 'Diana.yml').write_text('name: [unclosed\n', encoding='utf-8')

    assert [agent.name for agent in load(tmp_path).agents] == [agent.name for agent in AGENTS]


def cloud_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == '/api/agents':
            return httpx.Response(200, json=[CLOUD_AGENT])
        if request.url.path == '/api/providers':
            return httpx.Response(200, json=[CLOUD_PROVIDER])
        return httpx.Response(404, json={'error': {'code': 'NOT_FOUND', 'message': request.url.path}})

    return httpx.MockTransport(handler)


def empty_cloud_transport(created: list[dict]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == '/api/agents':
            if request.method == 'POST':
                agent_info = json.loads(request.content)
                agent_info['id'] = f'id-{len(created)}'
                created.append(agent_info)
                return httpx.Response(200, json=agent_info)
            return httpx.Response(200, json=created)
        if request.url.path == '/api/providers':
            return httpx.Response(200, json=[])
        return httpx.Response(404, json={'error': {'code': 'NOT_FOUND', 'message': request.url.path}})

    return httpx.MockTransport(handler)


async def test_an_empty_cloud_is_seeded_with_the_presets(tmp_path: Path):
    (config_dir(tmp_path) / 'cloud.yml').write_text(CLOUD_YML, encoding='utf-8')
    created: list[dict] = []

    config_mgr = ConfigManager(str(tmp_path), cloud_transport=empty_cloud_transport(created))
    await config_mgr.load()
    try:
        assert [agent.name for agent in config_mgr.agents] == [agent.name for agent in AGENTS]
        assert [agent['name'] for agent in created] == [agent.name for agent in AGENTS]
    finally:
        await config_mgr.aclose()


async def test_a_configured_cloud_is_loaded_instead_of_the_local_files(tmp_path: Path):
    (config_dir(tmp_path) / 'cloud.yml').write_text(CLOUD_YML, encoding='utf-8')
    (tmp_path / 'agents' / 'Diana.yml').write_text(DIANA_YML, encoding='utf-8')

    config_mgr = ConfigManager(str(tmp_path), cloud_transport=cloud_transport())
    await config_mgr.load()
    try:
        assert [agent.name for agent in config_mgr.agents] == ['CloudDiana']
        assert config_mgr.agents[0].description == 'from cloud'
        assert config_mgr.agents[0].prompts[0].params()['agent_name'] == 'CloudDiana'
        assert [provider.name for provider in config_mgr.providers] == ['cloud-p']
        assert config_mgr.providers[0].priority == 2
        assert config_mgr.providers[0].model_name == 'test-model'
        assert config_mgr.providers[0].thinking == 'disabled'
        assert not (tmp_path / 'providers.yml').exists()
    finally:
        await config_mgr.aclose()


async def test_a_disabled_cloud_leaves_the_local_files_alone(tmp_path: Path):
    (config_dir(tmp_path) / 'cloud.yml').write_text('enabled: false\nurl: https://cloud.test\napi_key: secret\n', encoding='utf-8')
    (tmp_path / 'agents' / 'Diana.yml').write_text(DIANA_YML, encoding='utf-8')

    config_mgr = ConfigManager(str(tmp_path))
    await config_mgr.load()

    assert config_mgr.cloud_client is None
    assert [agent.name for agent in config_mgr.agents] == ['Diana']


async def test_an_incomplete_cloud_config_falls_back_to_the_local_files(tmp_path: Path):
    (config_dir(tmp_path) / 'cloud.yml').write_text('enabled: true\napi_key: secret\n', encoding='utf-8')
    (tmp_path / 'agents' / 'Diana.yml').write_text(DIANA_YML, encoding='utf-8')

    config_mgr = ConfigManager(str(tmp_path))
    await config_mgr.load()

    assert config_mgr.cloud_client is None
    assert [agent.name for agent in config_mgr.agents] == ['Diana']


async def test_the_cloud_client_is_closed_by_aclose(tmp_path: Path):
    (config_dir(tmp_path) / 'cloud.yml').write_text(CLOUD_YML, encoding='utf-8')

    config_mgr = ConfigManager(str(tmp_path), cloud_transport=cloud_transport())
    await config_mgr.load()
    assert config_mgr.cloud_client is not None
    await config_mgr.aclose()

    assert config_mgr.cloud_client._client.is_closed


def test_a_missing_cloud_file_is_created_with_the_defaults(tmp_path: Path):
    config_mgr = load(tmp_path)

    assert config_mgr.cloud_client is None
    assert (tmp_path / 'cloud.yml').exists()
    assert IoHelper().read(tmp_path / 'cloud.yml') == CLOUD


def test_an_existing_cloud_file_is_never_overwritten(tmp_path: Path):
    (config_dir(tmp_path) / 'cloud.yml').write_text(CLOUD_YML, encoding='utf-8')

    ConfigManager(str(tmp_path))

    assert IoHelper().read(tmp_path / 'cloud.yml') == {'enabled': True, 'url': 'https://cloud.test', 'api_key': 'secret'}


async def test_the_created_cloud_file_keeps_the_local_flow(tmp_path: Path):
    (config_dir(tmp_path) / 'agents' / 'Diana.yml').write_text(DIANA_YML, encoding='utf-8')

    config_mgr = ConfigManager(str(tmp_path))
    await config_mgr.load()

    assert config_mgr.cloud_client is None
    assert [agent.name for agent in config_mgr.agents] == ['Diana']


def default_transport(state: dict) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == '/api/agents':
            return httpx.Response(200, json=[CLOUD_AGENT])
        if request.url.path == '/api/providers':
            return httpx.Response(200, json=[])
        if request.url.path == '/api/agent-defaults/TUI':
            state['calls'].append(request)
            if request.method == 'PUT':
                state['default'] = json.loads(request.content)
            if request.method == 'DELETE':
                state['default'] = None
                return httpx.Response(204)
            if state['default'] is None:
                return httpx.Response(404, json={'error': {'code': 'NOT_FOUND', 'message': 'Agent default not found.'}})
            return httpx.Response(200, json={'id': 'd1', 'source': 'TUI', **state['default']})
        return httpx.Response(404, json={'error': {'code': 'NOT_FOUND', 'message': request.url.path}})

    return httpx.MockTransport(handler)


async def test_a_cloud_agent_carries_its_id(tmp_path: Path):
    (config_dir(tmp_path) / 'cloud.yml').write_text(CLOUD_YML, encoding='utf-8')

    config_mgr = ConfigManager(str(tmp_path), cloud_transport=default_transport({'default': None, 'calls': []}))
    await config_mgr.load()
    try:
        assert config_mgr.agents[0].id == CLOUD_AGENT['id']
    finally:
        await config_mgr.aclose()


def test_a_local_agent_has_no_id(tmp_path: Path):
    (config_dir(tmp_path) / 'agents' / 'Diana.yml').write_text(DIANA_YML, encoding='utf-8')

    assert load(tmp_path).agents[0].id == ''


async def test_no_default_is_read_without_a_source(tmp_path: Path):
    (config_dir(tmp_path) / 'cloud.yml').write_text(CLOUD_YML, encoding='utf-8')
    state: dict = {'default': {'agent_id': CLOUD_AGENT['id']}, 'calls': []}

    config_mgr = ConfigManager(str(tmp_path), cloud_transport=default_transport(state))
    await config_mgr.load()
    try:
        assert config_mgr.default_agent is None
        assert state['calls'] == []
    finally:
        await config_mgr.aclose()


async def test_the_default_of_the_source_is_loaded(tmp_path: Path):
    (config_dir(tmp_path) / 'cloud.yml').write_text(CLOUD_YML, encoding='utf-8')
    state: dict = {'default': {'agent_id': CLOUD_AGENT['id']}, 'calls': []}

    config_mgr = ConfigManager(str(tmp_path), cloud_transport=default_transport(state), source='TUI')
    await config_mgr.load()
    try:
        assert config_mgr.default_agent is config_mgr.agents[0]
        assert [request.method for request in state['calls']] == ['GET']
    finally:
        await config_mgr.aclose()


async def test_a_source_without_a_default_has_none(tmp_path: Path):
    (config_dir(tmp_path) / 'cloud.yml').write_text(CLOUD_YML, encoding='utf-8')
    state: dict = {'default': None, 'calls': []}

    config_mgr = ConfigManager(str(tmp_path), cloud_transport=default_transport(state), source='TUI')
    await config_mgr.load()
    try:
        assert config_mgr.default_agent is None
    finally:
        await config_mgr.aclose()


async def test_a_default_pointing_at_an_agent_the_cloud_no_longer_serves_is_ignored(tmp_path: Path):
    (config_dir(tmp_path) / 'cloud.yml').write_text(CLOUD_YML, encoding='utf-8')
    state: dict = {'default': {'agent_id': '049e9b11-0000-4b97-92a5-000000000000'}, 'calls': []}

    config_mgr = ConfigManager(str(tmp_path), cloud_transport=default_transport(state), source='TUI')
    await config_mgr.load()
    try:
        assert config_mgr.default_agent is None
    finally:
        await config_mgr.aclose()


async def test_setting_a_default_puts_the_agent_id(tmp_path: Path):
    (config_dir(tmp_path) / 'cloud.yml').write_text(CLOUD_YML, encoding='utf-8')
    state: dict = {'default': None, 'calls': []}

    config_mgr = ConfigManager(str(tmp_path), cloud_transport=default_transport(state), source='TUI')
    await config_mgr.load()
    try:
        agent = config_mgr.agents[0]
        await config_mgr.set_default_agent(agent)

        assert config_mgr.default_agent is agent
        assert [request.method for request in state['calls']] == ['GET', 'PUT']
        assert json.loads(state['calls'][1].content) == {'agent_id': CLOUD_AGENT['id']}
    finally:
        await config_mgr.aclose()


async def test_clearing_a_default_deletes_it(tmp_path: Path):
    (config_dir(tmp_path) / 'cloud.yml').write_text(CLOUD_YML, encoding='utf-8')
    state: dict = {'default': {'agent_id': CLOUD_AGENT['id']}, 'calls': []}

    config_mgr = ConfigManager(str(tmp_path), cloud_transport=default_transport(state), source='TUI')
    await config_mgr.load()
    try:
        assert await config_mgr.clear_default_agent() is True

        assert config_mgr.default_agent is None
        assert [request.method for request in state['calls']] == ['GET', 'DELETE']
    finally:
        await config_mgr.aclose()


async def test_a_local_agent_cannot_be_a_default(tmp_path: Path):
    (config_dir(tmp_path) / 'cloud.yml').write_text(CLOUD_YML, encoding='utf-8')
    state: dict = {'default': None, 'calls': []}

    config_mgr = ConfigManager(str(tmp_path), cloud_transport=default_transport(state), source='TUI')
    await config_mgr.load()
    try:
        with pytest.raises(ValueError):
            await config_mgr.set_default_agent(AGENTS[0])
    finally:
        await config_mgr.aclose()


async def test_a_default_cannot_be_set_without_a_source(tmp_path: Path):
    (config_dir(tmp_path) / 'cloud.yml').write_text(CLOUD_YML, encoding='utf-8')
    state: dict = {'default': None, 'calls': []}

    config_mgr = ConfigManager(str(tmp_path), cloud_transport=default_transport(state))
    await config_mgr.load()
    try:
        with pytest.raises(ValueError):
            await config_mgr.set_default_agent(config_mgr.agents[0])
    finally:
        await config_mgr.aclose()


async def test_a_default_needs_a_configured_cloud(tmp_path: Path):
    (config_dir(tmp_path) / 'agents' / 'Diana.yml').write_text(DIANA_YML, encoding='utf-8')

    config_mgr = ConfigManager(str(tmp_path), source='TUI')
    await config_mgr.load()

    with pytest.raises(DataCloudError) as info:
        await config_mgr.set_default_agent(config_mgr.agents[0])
    assert info.value.code == 'NOT_CONFIGURED'
