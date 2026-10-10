import asyncio
import os

from rqark_core.types.chat import AssistantMessage, Chunk, Message, ToolCall, ToolMessage, Usage, UserMessage
from rqark_core.types.event import AgentPayload
from rqark_core.types.provider import Provider

from rqark_app.agent.agents import AgentHoliday
from rqark_app.app import AgentApp
from rqark_app.session.storage import JSONLStorage

"""
BadRequestError
Error code: 400 -
{'error': {'message': "This model's maximum context length is 1048576 tokens. However, you requested 1733194 tokens (1733194 in the messages, 0 in the completion). Please reduce the length of the messages or completion. (request_id: 6cef8dbf-0194-4db0-8964-3364e54fa9e4)", 'type': 'invalid_request_error', 'param': None, 'code': 'invalid_request_error'}}
{'error': {'message': 'Invalid request: Your request exceeded model token limit: 1048576 (requested: 1705112)', 'type': 'invalid_request_error'}}
"""

"""
OLLAMA_CONTEXT_LENGTH=2048 ollama serve
"""

model_name = 'qwen3.5:9b' # 'deepseek-r1:8b'
provider = Provider(model_name, 'api_key', 'http://127.0.0.1:11434/v1', 0, combine=True, thinking='disabled')
storage = JSONLStorage('./.sessions')
app = AgentApp([provider], storage)

@app.on_error()
async def has_error(ev: AgentPayload[Chunk]):
    print(ev.payload)

@app.on_message()
async def message(ev: AgentPayload[Message]):
    print(ev.payload)


@app.on_tool_result()
async def tool_result(ev: AgentPayload[ToolMessage]):
    print(ev.payload)


_pytest_log = '\n'.join(
    f'tests/test_retry_compact.py::test_case_{i:03d} FAILED - AssertionError: expected a Compact session, got None (prompt tokens {i * 37})'
    for i in range(1, 121)
)

_grep_hits = '\n'.join(
    f'src/rqark_app/compact/detect.py:{i}:    re.compile(r\'{pattern}\', re.IGNORECASE),'
    for i, pattern in enumerate(['prompt is too long', 'request_too_large', 'input is too long', 'maximum context length', 'too many tokens'], start=5)
)

_source = '\n'.join(
    f'{i}\t{"    " * (i % 4)}{line}'
    for i, line in enumerate(
        [
            'async def _loop(self, session: Session, core: AgentCore, agent: BaseAgent, history: list[Message]) -> Session:',
            'while True:',
            'provider = self.provider_mgr.provider',
            'new_messages, error = await core.chat(provider, history, agent.prompts, agent.tools)',
            'history = list(new_messages)',
            'session.update_history_to_last_chunk(history)',
            'await self.session_mgr.save(session.uuid)',
            'if error is None:',
            'return session',
            'if not isinstance(error, APIError):',
            'raise error',
            'await self.chat_helper.report_failure(core, provider)',
        ]
        * 12,
        start=47,
    )
)

_history: list[Message] = [
    UserMessage('今日的工作是什麽？'),
    AssistantMessage('今天的工作包括:\n1. 調查AI巿場情況。\n2. 下午三點和 Diana 開會討論Red Queen Ark 計劃最新發展方向。'),
    UserMessage('先幫我睇下 rqark-app 而家嘅 test 情況。'),
    AssistantMessage(
        '',
        tool_calls=[ToolCall('call_1', 'function', 'exec', '{"command": "uv run pytest -q"}')],
    ),
    ToolMessage('call_1', _pytest_log, 'exec', '{"command": "uv run pytest -q"}'),
    AssistantMessage(
        '測試好差，120 個 case 全部 fail，全部都係壓縮相關嘅 assert。我去睇下 detect.py 同 app.py。',
        usage=Usage(prompt_tokens=3812, completion_tokens=96, total_tokens=3908),
    ),
    UserMessage('好，順手搵埋邊度寫住 context overflow。'),
    AssistantMessage(
        '',
        tool_calls=[ToolCall('call_2', 'function', 'grep', '{"pattern": "context", "path": "src/rqark_app"}')],
    ),
    ToolMessage('call_2', _grep_hits, 'grep', '{"pattern": "context", "path": "src/rqark_app"}'),
    AssistantMessage(
        '搵到咗，全部 pattern 都係集中喺 compact/detect.py。',
        usage=Usage(prompt_tokens=4004, completion_tokens=64, total_tokens=4068),
    ),
    AssistantMessage(
        '',
        tool_calls=[ToolCall('call_3', 'function', 'read_file', '{"path": "src/rqark_app/app.py"}')],
    ),
    ToolMessage('call_3', _source, 'read_file', '{"path": "src/rqark_app/app.py"}'),
    UserMessage('噢，今日個會議我想取消'),
    AssistantMessage('明白，我幫你聯絡 Diana。'),
    UserMessage('Good, 同想你問下 Anson 得唔得閒搞搞 Bug Fix 先。'),
    AssistantMessage('沒問題，Boss。Anson 話下星期一開始。'),
    UserMessage('話說今天天氣唔錯'),
    AssistantMessage('天氣預報話今日晴天'),
]


async def main():
    await app.session_mgr.load()
    session = await app.session_mgr.create('test')
    session.history = list(_history)
    await app.session_mgr.save('test')
    await app.chat('我今日第一個工作係咩? 同埋頭先 pytest 邊幾個 case fail?', AgentHoliday(), 'test')


if __name__ == '__main__':
    asyncio.run(main())
