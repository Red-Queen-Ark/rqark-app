from rqark_app.agent.manager import AgentManager
from rqark_app.types.agent import BaseAgent


def build_agent(name: str) -> BaseAgent:
    built = BaseAgent()
    built.name = name
    built.description = ''
    built.prompts = []
    built.tools = []
    return built


def test_the_first_agent_is_current_without_a_default():
    mgr = AgentManager([build_agent('a'), build_agent('b')])

    assert mgr.agent.name == 'a'


def test_the_default_agent_is_current():
    second = build_agent('b')

    mgr = AgentManager([build_agent('a'), second], second)

    assert mgr.agent is second


def test_a_default_that_is_not_in_the_list_keeps_the_first_agent():
    mgr = AgentManager([build_agent('a'), build_agent('b')], build_agent('c'))

    assert mgr.agent.name == 'a'


def test_switch_to_moves_off_the_default():
    second = build_agent('b')
    mgr = AgentManager([build_agent('a'), second], second)

    assert mgr.switch_to(0) is True
    assert mgr.agent.name == 'a'
