from rqark_core.tools import WebSearch, WebFetch, PlanUpdate, Grep, ListDir, ReadFile, WriteFile, EditFile, Exec, SubAgent
from rqark_core.prompts import AgentsMdPrompt, DateTimePrompt, GitProjectPrompt, PlatformPrompt, RolePrompt, AntiSycophancyPrompt
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