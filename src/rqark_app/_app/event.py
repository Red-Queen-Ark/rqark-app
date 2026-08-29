from collections.abc import Callable

from rqark_core.libs.event import BaseEventEmitter, EventFunction
from rqark_core.types.chat import Chunk, Message, ToolMessage
from rqark_app.types.event import AgentAppEventType
from rqark_core.types.tool import PlanItem

class AgentAppEventEmitter(BaseEventEmitter[AgentAppEventType]):
    def on_think(self) -> Callable[[EventFunction[Chunk]], EventFunction[Chunk]]:
        return self._on("think")

    def on_content(self) -> Callable[[EventFunction[Chunk]], EventFunction[Chunk]]:
        return self._on("content")

    def on_tool_calls(self) -> Callable[[EventFunction[Chunk]], EventFunction[Chunk]]:
        return self._on("tool_calls")

    def on_tool_result(self) -> Callable[[EventFunction[ToolMessage]], EventFunction[ToolMessage]]:
        return self._on("tool_result")

    def on_error(self) -> Callable[[EventFunction[Chunk]], EventFunction[Chunk]]:
        return self._on("error")

    def on_message(self) -> Callable[[EventFunction[Message]], EventFunction[Message]]:
        return self._on("message")

    def on_plan(self) -> Callable[[EventFunction[PlanItem]], EventFunction[PlanItem]]:
        return self._on("plan")

    async def handle_chunk_event(self, chunk: Chunk):
        if chunk.type == 'reasoning_content':
            await self._emit('think', chunk)
        elif chunk.type == 'content':
            await self._emit('content', chunk)
        elif chunk.type == 'tool_calls' and isinstance(chunk.content, list):
            for call in chunk.content:
                print(call.name, call.arguments)
        elif chunk.type == 'tool_result' and isinstance(chunk.content, ToolMessage):
            await self._emit('tool_result', chunk)
        elif chunk.type == 'error':
            await self._emit('error', chunk)
    
    async def hendle_message_event(self, message: Message):
        await self._emit('message', message)
        
    async def handle_plan(self, plan_items: PlanItem):
        await self._emit('plan', plan_items)