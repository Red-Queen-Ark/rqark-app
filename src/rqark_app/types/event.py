from dataclasses import dataclass
from typing import Literal

from rqark_core.types.provider import Provider

type AgentAppEventType = Literal['think', 'content', 'tool_calls', 'tool_result', 'usage', 'error', 'message', 'plan', 'provider_switched']


@dataclass
class ProviderSwitch:
    old: Provider
    new: Provider
