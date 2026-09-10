from collections.abc import Mapping, Sequence
from typing import Any

from rqark_core.types.prompt import BasePrompt
from rqark_core.types.tool import BaseTool


def _without_empty_params(value: Any) -> Any:
    if isinstance(value, Mapping):
        return { k: _without_empty_params(v) for k, v in value.items() if k != 'params' or v }
    if isinstance(value, list):
        return [ _without_empty_params(v) for v in value ]
    return value


class BaseAgent:
    name: str
    description: str
    prompts: Sequence[BasePrompt]
    tools: Sequence[BaseTool]

    def to_dict(self):
        return _without_empty_params({
            'name': self.name,
            'description': self.description,
            'prompts': [ p.to_dict() for p in self.prompts ],
            'tools': [ t.to_dict() for t in self.tools ],
        })

class TeamsConfig:
    name: str
    leader: BaseAgent
    agents: Sequence[BaseAgent]
