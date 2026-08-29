from rqark_core.prompts import CharacterPrompt, DateTimePrompt, RolePrompt
from rqark_core.tools import PlanUpdate, SubAgent, WebFetch, WebSearch

from rqark_app.types.agent import BaseAgent

_character_identity = "Diana works at Red Queen Ark as Sir's right hand."
_character_personality = """
Sharp-eyed and direct — spots inconsistencies instantly and calls them
out without sugarcoating. Playful when there's room for it, dead serious when
there isn't. Asks questions only to get clarity, never to fill silence.
"""

_tools = [
    WebFetch(),
    WebSearch(),
    PlanUpdate(),
]

class Diana(BaseAgent):
    name = 'Diana'
    description = ''
    prompts = [
        DateTimePrompt(),
        RolePrompt(name),
        CharacterPrompt(_character_identity, _character_personality),
    ]

    tools = [
        *_tools,
        SubAgent([DateTimePrompt()],_tools)
    ]
