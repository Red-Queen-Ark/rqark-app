from typing import Literal
from rqark_core.core import AgentCore
from rqark_core.types.tool import BaseTool
from rqark_core.types.prompt import BasePrompt
from rqark_core.types.provider import Provider
from rqark_app.provider.manager import ProviderManager
from rqark_app.types.agent import AgentConfig, TeamsConfig

class AgentApp:
    def __init__(self, providers: list[Provider]):
        self.provider_mgr = ProviderManager(providers)
        # self.session_mgr = 
        # self.event_mgr = 

    def chat(self):
        ...
