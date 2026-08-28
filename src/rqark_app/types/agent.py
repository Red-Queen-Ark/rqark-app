from dataclasses import dataclass
from collections.abc import Sequence
from rqark_core.types.prompt import BasePrompt
from rqark_core.types.tool import BaseTool

@dataclass
class BaseAgent:
    name: str
    description: str
    prompts: Sequence[BasePrompt]
    tools: Sequence[BaseTool]

@dataclass
class TeamsConfig:
    name: str
    leader: BaseAgent
    agents: Sequence[BaseAgent]