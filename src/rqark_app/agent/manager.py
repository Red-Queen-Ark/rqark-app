from collections.abc import Sequence

from rqark_app.types.agent import BaseAgent


class AgentManager:
    def __init__(self, agents: Sequence[BaseAgent]):
        self.agents: Sequence[BaseAgent] = agents
        self.cur_index = 0
        self.retry: int = 0

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
