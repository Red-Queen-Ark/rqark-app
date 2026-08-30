import asyncio

from model import MODEL_NAME
from rqark_core.types.chat import Chunk, ToolMessage
from rqark_core.types.event import AgentPayload

from rqark_app.agent.agents import Wednesday
from rqark_app.app import AgentApp, Provider, ProviderSwitch
from rqark_app.session.storage import JSONLStorage

provider = Provider(MODEL_NAME, 'api_key', 'http://127.0.0.1:8080', 0, combine=True, thinking='disabled')
storage = JSONLStorage('./session')
app = AgentApp([provider], storage)


@app.on_think()
async def thinking(ev: AgentPayload[Chunk]):
    print(ev)


@app.on_content()
async def content(ev: AgentPayload[Chunk]):
    print(ev)


@app.on_tool_calls()
async def tool_calls(ev: AgentPayload[Chunk]):
    print(ev)


@app.on_tool_result()
async def tool_result(ev: AgentPayload[ToolMessage]):
    print(ev)


@app.on_error()
async def has_error(ev: AgentPayload[Chunk]):
    print(ev)


@app.on_provider_switched()
async def switch_provider(ev: AgentPayload[ProviderSwitch]):
    print(ev)


async def main():
    await app.chat('你係邊個?', Wednesday())


if __name__ == '__main__':
    asyncio.run(main())
