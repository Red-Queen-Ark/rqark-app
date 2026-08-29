from collections.abc import Callable
from rqark_core.libs.event import BaseEventEmitter, EventFunction
from rqark_core.types.chat import Chunk, Message, ToolMessage
from rqark_app.types.event import AgentAppEventType

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

    async def _emit_think(self, chunk: Chunk) -> None:
        await self._emit("think", chunk)

    async def _emit_content(self, chunk: Chunk) -> None:
        await self._emit("content", chunk)

    async def _emit_tool_calls(self, chunk: Chunk) -> None:
        await self._emit("tool_calls", chunk)

    async def _emit_tool_result(self, tool_msg: ToolMessage) -> None:
        await self._emit("tool_result", tool_msg)

    async def _emit_error(self, chunk: Chunk) -> None:
        await self._emit("error", chunk)

    async def _emit_message(self, message: Message) -> None:
        await self._emit("message", message)
