from collections.abc import Sequence
from pathlib import Path

from rqark_core.types.provider import Provider

from rqark_app.config.default import AGENTS, PROVIDERS
from rqark_app.config.dir_cache import DirCache
from rqark_app.libs.io import IoHelper
from rqark_app.types.agent import BaseAgent


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

    def _load_agents(self):
        path = self.config_path / 'agents'
        path.mkdir(parents=True, exist_ok=True)
        agent_config_list = list( path.glob('*.yml'))
        if not agent_config_list:
            self._create_default_agent_config(path)
        # for agent_config_path in agent_config_list:
        #     agent_info = self.io_helper.read(agent_config_path)
        #     if agent_info:
        #         ...
    
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
