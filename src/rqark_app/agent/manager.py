from collections.abc import Sequence

from rqark_app.types.agent import BaseAgent


class AgentManager:
    def __init__(self, agents: Sequence[BaseAgent], default: BaseAgent | None = None):
        self.agents: Sequence[BaseAgent] = agents
        self.cur_index = self._index_of(default)
        self.retry: int = 0

    def _index_of(self, default: BaseAgent | None) -> int:
        if default is None:
            return 0
        for index, agent in enumerate(self.agents):
            if agent is default:
                return index
        for index, agent in enumerate(self.agents):
            if agent.name == default.name:
                return index
        return 0

    @property
    def agent(self) -> BaseAgent:
        return self.agents[self.cur_index]

    def _switch_provider(self) -> None:
        self.cur_index += 1
        if self.cur_index >= len(self.agents):
            self.cur_index = 0

    def switch_to(self, index: int) -> bool:
        if index < 0 or index >= len(self.agents):
            return False
        if index == self.cur_index:
            return True
        self.cur_index = index
        self.retry = 0
        return True
