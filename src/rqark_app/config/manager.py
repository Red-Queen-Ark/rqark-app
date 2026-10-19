from collections.abc import Callable, Sequence
from pathlib import Path

import httpx
from rqark_core.prompts import AgentsMdPrompt, AntiSycophancyPrompt, CharacterPrompt, DateTimePrompt, GitProjectPrompt, PlatformPrompt, RolePrompt, SubAgentPrompt, WorkspacePrompt
from rqark_core.tools import EditFile, Exec, Gitea, GitHub, GitLab, Grep, ListDir, PlanUpdate, ReadFile, SubAgent, WebFetch, WebSearch, WriteFile
from rqark_core.types.prompt import BasePrompt
from rqark_core.types.provider import Provider
from rqark_core.types.tool import BaseTool

from rqark_app.cloud.client import DataCloudError, RQArkDataCloudClient
from rqark_app.config.default import AGENTS, CLOUD, PROVIDERS
from rqark_app.config.dir_cache import DirCache
from rqark_app.libs.io import IoHelper
from rqark_app.prompts.memory import MemoryPrompt
from rqark_app.prompts.state import StatePrompt
from rqark_app.sop.manager import SopManager
from rqark_app.tools import MemorySave, MemorySearch, Task, Todo
from rqark_app.types.agent import BaseAgent
from rqark_app.types.cloud import CloudConfig

PROMPTS: dict[str, Callable[..., BasePrompt]] = {
    'AgentsMdPrompt': AgentsMdPrompt,
    'AntiSycophancyPrompt': AntiSycophancyPrompt,
    'CharacterPrompt': CharacterPrompt,
    'DateTimePrompt': DateTimePrompt,
    'GitProjectPrompt': GitProjectPrompt,
    'MemoryPrompt': MemoryPrompt,
    'PlatformPrompt': PlatformPrompt,
    'RolePrompt': RolePrompt,
    'StatePrompt': StatePrompt,
    'SubAgentPrompt': SubAgentPrompt,
    'WorkspacePrompt': WorkspacePrompt,
}

TOOLS: dict[str, Callable[..., BaseTool]] = {
    'EditFile': EditFile,
    'Exec': Exec,
    'Gitea': Gitea,
    'GitHub': GitHub,
    'GitLab': GitLab,
    'Grep': Grep,
    'ListDir': ListDir,
    'MemorySave': MemorySave,
    'MemorySearch': MemorySearch,
    'PlanUpdate': PlanUpdate,
    'ReadFile': ReadFile,
    'Task': Task,
    'Todo': Todo,
    'WebFetch': WebFetch,
    'WebSearch': WebSearch,
    'WriteFile': WriteFile,
}

PROVIDER_FIELDS = frozenset(Provider.__dataclass_fields__)


def _agent_config_paths(path: Path) -> list[Path]:
    return sorted(p for p in path.iterdir() if p.is_file() and p.suffix in {'.yml', '.yaml'})


def _build_prompt(info: dict) -> BasePrompt:
    return PROMPTS[info['name']](**(info.get('params') or {}))


def _build_tool(info: dict) -> BaseTool:
    params = info.get('params') or {}
    if info['name'] == 'SubAgent':
        prompts = [_build_prompt(p) for p in params.get('prompts', [])]
        tools = [_build_tool(t) for t in params.get('tools', [])]
        return SubAgent(prompts, tools)
    return TOOLS[info['name']](**params)


def _build_provider(info: dict) -> Provider:
    return Provider(**{key: value for key, value in info.items() if key in PROVIDER_FIELDS})


def _build_agent(agent_info: dict) -> BaseAgent:
    agent = BaseAgent()
    agent.id = str(agent_info.get('id') or '')
    agent.name = agent_info['name']
    agent.description = agent_info.get('description', '')
    agent.prompts = [_build_prompt(p) for p in agent_info.get('prompts', [])]
    agent.tools = [_build_tool(t) for t in agent_info.get('tools', [])]
    return agent


class ConfigManager:
    def __init__(self, config_path: str, cloud_transport: httpx.AsyncBaseTransport | None = None, source: str = ''):
        self.io_helper = IoHelper()
        self.config_path = Path(config_path)
        self.cloud_transport = cloud_transport
        self.source = source

        self.agents: Sequence[BaseAgent] = []
        self.providers: list[Provider] = []
        self.default_agent: BaseAgent | None = None

        self.dir_cache = DirCache(self.config_path)
        self.cwd_hash = self.dir_cache.compute_hash(Path.cwd())

        self.cloud_client: RQArkDataCloudClient | None = None
        self.sop_manager = SopManager(self.config_path)

    async def load(self):
        self.config_path.mkdir(parents=True, exist_ok=True)
        self._load_cloud()
        await self._load_agents()
        await self._load_default_agent()
        await self._load_providers()

    async def aclose(self):
        if self.cloud_client is not None:
            await self.cloud_client.aclose()

    async def set_default_agent(self, agent: BaseAgent) -> None:
        client = self._agent_default_client()
        if not agent.id:
            raise ValueError('a default agent has to come from the data cloud')
        await client.set_agent_default(self._default_source(), agent.id)
        self.default_agent = agent

    async def clear_default_agent(self) -> bool:
        cleared = await self._agent_default_client().delete_agent_default(self._default_source())
        self.default_agent = None
        return cleared

    def _load_cloud(self):
        path = self.config_path / 'cloud.yml'
        if not path.exists():
            self.io_helper.save(path, CLOUD)
        info = self.io_helper.read(path) or {}
        config = CloudConfig(bool(info.get('enabled')), str(info.get('url') or ''), str(info.get('api_key') or ''))
        if config.configured:
            self.cloud_client = RQArkDataCloudClient(config, transport=self.cloud_transport)
        self.sop_manager = SopManager(self.config_path, self.cloud_client)

    async def _load_agents(self):
        if self.cloud_client is not None:
            self.agents = await self._load_cloud_agents(self.cloud_client)
            return
        path = self.config_path / 'agents'
        path.mkdir(parents=True, exist_ok=True)
        agent_config_list = _agent_config_paths(path)
        if not agent_config_list:
            self._create_default_agent_config(path)
            agent_config_list = _agent_config_paths(path)
        agents: list[BaseAgent] = []
        for agent_config_path in agent_config_list:
            agent_info = self.io_helper.read(agent_config_path)
            if agent_info:
                agents.append(_build_agent(agent_info))
        if not agents:
            agents = list(AGENTS)
        self.agents = agents

    async def _load_cloud_agents(self, client: RQArkDataCloudClient) -> list[BaseAgent]:
        agent_info_list = await client.list_agents()
        if agent_info_list:
            return [_build_agent(agent_info) for agent_info in agent_info_list]
        agents: list[BaseAgent] = []
        for agent in AGENTS:
            created = await client.create_agent(agent.to_dict())
            agents.append(_build_agent(created) if created else agent)
        return agents

    async def _load_default_agent(self):
        if self.cloud_client is None or not self.source:
            return
        info = await self.cloud_client.get_agent_default(self.source)
        if info:
            self.default_agent = self._agent_with_id(info.get('agent_id') or '')

    def _agent_with_id(self, agent_id: str) -> BaseAgent | None:
        for agent in self.agents:
            if agent.id and agent.id == agent_id:
                return agent
        return None

    def _agent_default_client(self) -> RQArkDataCloudClient:
        if self.cloud_client is None:
            raise DataCloudError(0, 'NOT_CONFIGURED', 'agent defaults need a configured data cloud')
        return self.cloud_client

    def _default_source(self) -> str:
        if not self.source:
            raise ValueError('agent defaults need a source')
        return self.source

    def _create_default_agent_config(self, path: Path):
        for a in AGENTS:
            agent_file_name = a.name + '.yml'
            agent_file_name = agent_file_name.replace(' ', '_')
            agent_path = path / agent_file_name
            self.io_helper.save(agent_path, a.to_dict())

    async def _load_providers(self):
        if self.cloud_client is not None:
            self.providers = [_build_provider(provider) for provider in await self.cloud_client.list_providers()]
            return
        path = self.config_path / 'providers.yml'
        providers = self.io_helper.read(path)
        if providers is None:
            self.io_helper.save(path, PROVIDERS)
            self.providers = []
        else:
            self.providers = [Provider(**provider) for provider in providers]
