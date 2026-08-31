from rqark_core.types.prompt import BasePrompt

_prompt = """

"""

class CompactContext(BasePrompt):
    priority: int = -1
    
    def get_messages(self) -> str | None:
        return _prompt