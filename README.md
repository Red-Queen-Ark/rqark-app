# rqark-app

Session, provider and agent management on top of `rqark-core`, with an optional data cloud for memory, todos and settings.

## Why rqark-app

`rqark-core` runs one conversation. This keeps it: turns are stored and can be resumed, a failed provider rotates to the next one, and a finished turn is recorded without anyone calling a tool.

## Installation

Requires Python 3.14+.

```bash
uv add rqark-app
# or
pip install rqark-app
```

## Quick Start

```python
import asyncio

from rqark_core.types.chat import Chunk
from rqark_core.types.event import AgentPayload
from rqark_core.types.provider import Provider

from rqark_app.agent.agents import Wednesday
from rqark_app.app import AgentApp
from rqark_app.session.storage import JSONLStorage

provider = Provider(model_name='gpt-5', api_base='https://api.openai.com/v1', priority=0, api_key='sk-...')

app = AgentApp([provider], storage=JSONLStorage('./.sessions'))


@app.on_content()
async def print_content(ev: AgentPayload[Chunk]):
    print(ev.payload.content, end='', flush=True)


async def main():
    session = await app.chat('Who are you?', Wednesday(), path=('demo',))
    print(session.uuid)


asyncio.run(main())
```

## App

### Events

- `on_think`
- `on_content`
- `on_tool_calls`
- `on_tool_result`
- `on_usage`
- `on_error`
- `on_message`
- `on_plan`
- `on_provider_switched`

### Retry

`APIError` reports a failure to the `ProviderManager`; three consecutive failures rotate the provider. A context overflow asks the `Compactor` for a summary, appends it to the history, and retries from the last chunk. Anything else is raised.

`session.plan_items` is seeded back into each new core, so `plan_update` sees the running plan instead of "No active plan".

## Managers

### Session

- `SessionManager`
- `Session`
- `SessionStorage`
- `JSONLStorage`
- `CloudStorage`

### Provider

- `ProviderManager`

### Agent

- `AgentManager`
- `BaseAgent`
- `Wednesday`
- `Diana`
- `AgentHoliday`

### Config

- `ConfigManager`
- `DirCache`
- `SopManager`

## Cloud

`cloud.yml` needs `enabled`, `url` and `api_key`. Once configured the cloud is the only source; there is no fallback to local files and a failed load raises `DataCloudError`.

- `RQArkDataCloudClient`
- `CloudStorage`
- `DataCloudError` — `REQUEST_FAILED` unreachable, `INVALID_RESPONSE` not JSON, anything else is a 4xx/5xx from the cloud

### Default agent

One per `source`, stored in the cloud and shared across clients. `set_default_agent()` and `clear_default_agent()` write it back; the agent needs an `id` from the cloud.

## Memory

- `TurnMemoryWriter`
- `MemorySettings`
- `MemorySave`
- `MemorySearch`

## Tools

### Memory

- `MemorySave`
- `MemorySearch`

### Cloud

- `Todo`
- `Task`

## SOP

- `SopManager`
- `Sop`
