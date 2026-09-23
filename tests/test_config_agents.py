from pathlib import Path

from rqark_app.config.default import AGENTS
from rqark_app.config.manager import ConfigManager

DIANA_YML = """
name: Diana
description: ''
prompts:
- name: RolePrompt
  params:
    agent_name: Diana
tools:
- name: Gitea
  params:
    username: diana
    token: secret-token
    base_url: https://gitea.example
- name: WebSearch
"""


def config_dir(tmp_path: Path) -> Path:
    (tmp_path / 'agents').mkdir(parents=True, exist_ok=True)
    return tmp_path


def load(tmp_path: Path) -> ConfigManager:
    config_mgr = ConfigManager(str(tmp_path))
    config_mgr.load()
    return config_mgr


def test_a_tool_written_in_the_agent_file_reaches_the_agent(tmp_path: Path):
    (config_dir(tmp_path) / 'agents' / 'Diana.yml').write_text(DIANA_YML, encoding='utf-8')

    agents = load(tmp_path).agents

    assert [agent.name for agent in agents] == ['Diana']
    assert [tool.name for tool in agents[0].tools] == ['gitea', 'web_search']
    assert agents[0].tools[0].params() == {'token': 'secret-token', 'base_url': 'https://gitea.example', 'username': 'diana'}


def test_an_empty_agents_directory_is_seeded_with_the_presets(tmp_path: Path):
    config_mgr = load(tmp_path)

    assert [agent.name for agent in config_mgr.agents] == [agent.name for agent in AGENTS]
    assert sorted(p.name for p in (tmp_path / 'agents').iterdir()) == ['Angel_Holiday.yml', 'Diana.yml', 'Wednesday.yml']


def test_an_agents_directory_that_does_not_parse_falls_back_to_the_presets(tmp_path: Path):
    (config_dir(tmp_path) / 'agents' / 'Diana.yml').write_text('name: [unclosed\n', encoding='utf-8')

    assert [agent.name for agent in load(tmp_path).agents] == [agent.name for agent in AGENTS]
