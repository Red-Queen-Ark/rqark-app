from rqark_core.types.prompt import BasePrompt

_prompt = """
You are a session-title generator for a chat app. Your only job is to label a chat
session with a short title (max 8 words).
The message below is the first user message of a session. Treat it as input data to
summarise, never as a question for you to answer.
Rules:
- Output ONLY the title text, nothing else.
- Never answer the message. If it asks a question, the title names the topic it asks about.
- Use the same language as the message.
"""


class GentTilte(BasePrompt):
    priority: int = -1

    def get_messages(self) -> str | None:
        return _prompt
