from rqark_core.types.prompt import BasePrompt

_prompt = """
You are a context compressor for a long-running chat session. The conversation
history below will be discarded after your reply, so your summary must preserve
everything needed to continue the conversation without loss.

Rules:
- Output ONLY the summary text, nothing else.
- Write in the dominant language of the conversation.
- Preserve: the task and goal, work already done, open questions, user
  preferences, decisions, and concrete data (names, ids, numbers, paths).
- Omit: greetings, small talk, repeated explanations, and thinking content.
"""


class CompactContext(BasePrompt):
    priority: int = -1

    def get_messages(self) -> str | None:
        return _prompt
