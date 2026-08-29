from rqark_core.prompts import AgentsMdPrompt, AntiSycophancyPrompt, DateTimePrompt, GitProjectPrompt, PlatformPrompt, RolePrompt
from rqark_core.tools import EditFile, Exec, Grep, ListDir, PlanUpdate, ReadFile, SubAgent, WebFetch, WebSearch, WriteFile

from rqark_app.types.agent import BaseAgent

_prompts = [
    AgentsMdPrompt(),
    GitProjectPrompt(),
    PlatformPrompt(),
    DateTimePrompt(),
]

_tools = [
    WebFetch(),
    WebSearch(),
    PlanUpdate(),
    Grep(),
    ListDir(),
    ReadFile(),
    WriteFile(),
    EditFile(),
]

class AgentHoliday(BaseAgent):
    name = 'Angel Holiday'
    description = ''
    prompts = [
        *_prompts,
        AntiSycophancyPrompt(),
        RolePrompt(name, 'Boss'),
    ]
    tools = [
        *_tools,
        Exec(),
        SubAgent(_prompts, _tools)
    ]
