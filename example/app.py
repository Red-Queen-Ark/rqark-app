import asyncio

from model import MODEL_NAME
from rqark_core.types.chat import Chunk, ToolMessage

from rqark_app.agent.agents import Wednesday
from rqark_app.app import AgentApp, Provider

provider = Provider(MODEL_NAME, 'api_key', 'http://127.0.0.1:8080', 0, combine=True, thinking='disabled')

agents = [
    Wednesday(),
]

app = AgentApp( [provider], agents)

@app.on_think()
async def thinking(chunk: Chunk):
    print(chunk)

@app.on_content()
async def content(chunk: Chunk):
    print(chunk)

@app.on_tool_calls()
async def tool_calls(chunk: Chunk):
    print(chunk)

@app.on_tool_result()
async def tool_result(tool_msg: ToolMessage):
    print(tool_msg)

@app.on_error()
async def has_error(chunk: Chunk):
    print(chunk)

async def main():
    messages = await app.chat('你係邊個?')

if __name__ == "__main__":
    asyncio.run(main())
