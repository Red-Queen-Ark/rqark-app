from collections.abc import Callable

from rqark_core.libs.event import BaseEventEmitter, EventFunction
from rqark_core.types.chat import Chunk, Message, ToolMessage
from rqark_core.types.event import AgentPayload
from rqark_core.types.tool import PlanItem

from rqark_app.types.event import AgentAppEventType


class AgentAppEventEmitter(BaseEventEmitter[AgentAppEventType]):
    def on_think(self) -> Callable[[EventFunction[AgentPayload[Chunk]]], EventFunction[AgentPayload[Chunk]]]:
        return self._on('think')

    def on_content(self) -> Callable[[EventFunction[AgentPayload[Chunk]]], EventFunction[AgentPayload[Chunk]]]:
        return self._on('content')

    def on_tool_calls(self) -> Callable[[EventFunction[AgentPayload[Chunk]]], EventFunction[AgentPayload[Chunk]]]:
        return self._on('tool_calls')

    def on_tool_result(self) -> Callable[[EventFunction[AgentPayload[ToolMessage]]], EventFunction[AgentPayload[ToolMessage]]]:
        return self._on('tool_result')

    def on_error(self) -> Callable[[EventFunction[AgentPayload[Chunk]]], EventFunction[AgentPayload[Chunk]]]:
        return self._on('error')

    def on_message(self) -> Callable[[EventFunction[AgentPayload[Message]]], EventFunction[AgentPayload[Message]]]:
        return self._on('message')

    def on_plan(self) -> Callable[[EventFunction[AgentPayload[list[PlanItem]]]], EventFunction[AgentPayload[list[PlanItem]]]]:
        return self._on('plan')

    async def handle_chunk_event(self, ev: AgentPayload[Chunk]):
        chunk = ev.payload
        if chunk.type == 'reasoning_content':
            await self._emit('think', ev)
        elif chunk.type == 'content':
            await self._emit('content', ev)
        elif chunk.type == 'tool_calls' and isinstance(chunk.content, list):
            await self._emit('tool_calls', ev)
        elif chunk.type == 'tool_result' and isinstance(chunk.content, ToolMessage):
            await self._emit('tool_result', ev)
        elif chunk.type == 'error':
            await self._emit('error', ev)

    async def handle_message_event(self, ev: AgentPayload[Message]):
        await self._emit('message', ev)

    async def handle_plan(self, ev: AgentPayload[list[PlanItem]]):
        await self._emit('plan', ev)
