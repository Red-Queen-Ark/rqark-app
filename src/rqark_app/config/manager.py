from collections.abc import Callable, Sequence
from pathlib import Path

from rqark_core.prompts import AgentsMdPrompt, AntiSycophancyPrompt, CharacterPrompt, DateTimePrompt, GitProjectPrompt, PlatformPrompt, RolePrompt, SubAgentPrompt, WorkspacePrompt
from rqark_core.tools import EditFile, Exec, Gitea, GitHub, GitLab, Grep, ListDir, PlanUpdate, ReadFile, SubAgent, WebFetch, WebSearch, WriteFile
from rqark_core.types.prompt import BasePrompt
from rqark_core.types.provider import Provider
from rqark_core.types.tool import BaseTool

from rqark_app.types.cloud import CloudConfig
from rqark_app.config.default import AGENTS, PROVIDERS
from rqark_app.config.dir_cache import DirCache
from rqark_app.libs.io import IoHelper
from rqark_app.types.agent import BaseAgent

PROMPTS: dict[str, Callable[..., BasePrompt]] = {
    'AgentsMdPrompt': AgentsMdPrompt,
    'AntiSycophancyPrompt': AntiSycophancyPrompt,
    'CharacterPrompt': CharacterPrompt,
    'DateTimePrompt': DateTimePrompt,
    'GitProjectPrompt': GitProjectPrompt,
    'PlatformPrompt': PlatformPrompt,
    'RolePrompt': RolePrompt,
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
    'PlanUpdate': PlanUpdate,
    'ReadFile': ReadFile,
    'WebFetch': WebFetch,
    'WebSearch': WebSearch,
    'WriteFile': WriteFile,
}


def _agent_config_paths(path: Path) -> list[Path]:
    return sorted(p for p in path.iterdir() if p.is_file() and p.suffix in { '.yml', '.yaml' })


def _build_prompt(info: dict) -> BasePrompt:
    return PROMPTS[info['name']](**(info.get('params') or {}))


def _build_tool(info: dict) -> BaseTool:
    params = info.get('params') or {}
    if info['name'] == 'SubAgent':
        prompts = [ _build_prompt(p) for p in params.get('prompts', []) ]
        tools = [ _build_tool(t) for t in params.get('tools', []) ]
        return SubAgent(prompts, tools)
    return TOOLS[info['name']](**params)


class ConfigManager:
    def __init__(self, config_path: str):
        self.io_helper = IoHelper()
        self.config_path = Path(config_path)

        self.agents: Sequence[BaseAgent] = []
        self.providers: list[Provider] = []

        self.dir_cache = DirCache(self.config_path)
        self.cwd_hash = self.dir_cache.compute_hash(Path.cwd())

    def load(self):
        self.config_path.mkdir(parents=True, exist_ok=True)
        self._load_agents()
        self._load_providers()

    def _load_cloud(self):
        path = self.config_path / 'providers.yml'
        info = self.io_helper.read(path) or {}
        enabled = bool(info.get('enabled'))
        url = str(info.get('url') or '')
        api_key = str(info.get('api_key') or '')
        self.cloud = CloudConfig(enabled, url, api_key)

    def _load_agents(self):
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
                agents.append(self._build_agent(agent_info))
        if not agents:
            # Every file exists but none parsed, so fall back to the presets rather
            # than leaving the app with no agent to run.
            agents = list(AGENTS)
        self.agents = agents

    def _build_agent(self, agent_info: dict) -> BaseAgent:
        agent = BaseAgent()
        agent.name = agent_info['name']
        agent.description = agent_info.get('description', '')
        agent.prompts = [ _build_prompt(p) for p in agent_info.get('prompts', []) ]
        agent.tools = [ _build_tool(t) for t in agent_info.get('tools', []) ]
        return agent

    def _create_default_agent_config(self, path: Path):
        for a in AGENTS:
            agent_file_name =  (a.name + '.yml')
            agent_file_name = agent_file_name.replace(' ', '_')
            agent_path = path / agent_file_name
            self.io_helper.save(agent_path, a.to_dict())

    def _load_providers(self):
        path = self.config_path / 'providers.yml'
        providers = self.io_helper.read(path)
        if providers is None:
            self.io_helper.save(path, PROVIDERS)
            providers = []
        else:
            self.providers = [ Provider(**provider) for provider in providers]
