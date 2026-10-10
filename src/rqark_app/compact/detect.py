import re

from openai import BadRequestError

_CONTEXT_OVERFLOW_PATTERNS = (
    re.compile(r'prompt is too long', re.IGNORECASE),
    re.compile(r'request_too_large', re.IGNORECASE),
    re.compile(r'input is too long', re.IGNORECASE),
    re.compile(r'exceeds the context window', re.IGNORECASE),
    re.compile(r'maximum context length', re.IGNORECASE),
    re.compile(r'input token count.*exceeds the maximum', re.IGNORECASE),
    re.compile(r'tokens in request more than max tokens allowed', re.IGNORECASE),
    re.compile(r'maximum prompt length is \d+', re.IGNORECASE),
    re.compile(r'reduce the length of the messages', re.IGNORECASE),
    re.compile(r'exceeds (?:the )?maximum allowed input length', re.IGNORECASE),
    re.compile(r"is longer than the model'?s context length", re.IGNORECASE),
    re.compile(r'exceeds the available context size', re.IGNORECASE),
    re.compile(r'greater than the context length', re.IGNORECASE),
    re.compile(r'context window exceeds limit', re.IGNORECASE),
    re.compile(r'exceeded model token limit', re.IGNORECASE),
    re.compile(r'exceeds the context limit', re.IGNORECASE),
    re.compile(r'context[_ ]length[_ ]exceeded', re.IGNORECASE),
    re.compile(r'request entity too large', re.IGNORECASE),
    re.compile(r'context length is only \d+ tokens', re.IGNORECASE),
    re.compile(r'input length.*exceeds.*context length', re.IGNORECASE),
    re.compile(r'prompt too long', re.IGNORECASE),
    re.compile(r'too large for model with \d+ maximum context length', re.IGNORECASE),
    re.compile(r'model_context_window_exceeded', re.IGNORECASE),
    re.compile(r'too many tokens', re.IGNORECASE),
    re.compile(r'token limit exceeded', re.IGNORECASE),
)

_CONTEXT_OVERFLOW_EXCLUSIONS = (
    re.compile(r'rate limit', re.IGNORECASE),
    re.compile(r'too many requests', re.IGNORECASE),
    re.compile(r'throttl', re.IGNORECASE),
    re.compile(r'quota', re.IGNORECASE),
    re.compile(r'billing', re.IGNORECASE),
    re.compile(r'per (?:minute|hour|day)', re.IGNORECASE),
)


def is_context_overflow(error: Exception) -> bool:
    if not isinstance(error, BadRequestError):
        return False
    body = error.body
    if not isinstance(body, dict):
        return False
    raw = body.get('error', body)
    message = ''
    code = ''
    if isinstance(raw, dict):
        value = raw.get('message')
        message = value if isinstance(value, str) else ''
        value = raw.get('code')
        code = value if isinstance(value, str) else ''
    elif isinstance(raw, str):
        message = raw
    if code.lower() == 'context_length_exceeded':
        return True
    if not message:
        return False
    if any(pattern.search(message) for pattern in _CONTEXT_OVERFLOW_EXCLUSIONS):
        return False
    return any(pattern.search(message) for pattern in _CONTEXT_OVERFLOW_PATTERNS)
