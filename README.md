# rqark-app
## Overview
- 封裝 rqark-core，提供 Sessions, Agents, Provider 管理工具組
- 整合雲端服務(rqark-data-cloud - RQArkDataCloudClient)
- 細化 core Agent Event 接口

## Quick Start
在專案 `pyproject.toml` 中加入

```toml
[[tool.uv.index]]
name = "gitea"
url = "https://gitea.carhyme.top/api/packages/RedQueenArk/pypi/simple"
publish-url = "https://gitea.carhyme.top/api/packages/RedQueenArk/pypi"
explicit = true

[tool.uv.sources]
rqark-core = { index = "gitea" }
rqark-app = { index = "gitea" }
```

設定認證

```bash
uv auth login https://gitea.carhyme.top/api/packages/RedQueenArk/pypi/simple
```

安裝
```
uv add rqark-app
```

## Features
### Manager
#### Provider Manager
管理多個 Provider，按優先次序排列。當目前 Provider 連續失敗 3 次，會自動切換到下一個。

#### Agents Manager
管理 Agent 序列，提供當前 Agent 讀取 (`agent`) 同手動切換 (`switch_to`)。可選傳入 `default` 令預設 Agent 一開始就係當前 Agent。

```python
agent_mgr = AgentManager(config_mgr.agents, config_mgr.default_agent)
```

#### Session Manager
- 管理對話 Session，可選配 `SessionStorage` 持久化
- 內建 `JSONLStorage`，每個 Session 存成一個 `.jsonl`（首行 metadata，之後每行一個訊息）。

#### Config Manager
- 由設定目錄載入 agents 同 providers，透過 prompts/tools 註冊表建構物件，未設定時用內建預設
- `DirCache` 另外記錄每個工作目錄對應嘅 session ids。
- `cloud.yml` 一經啟用（`enabled` + `url` + `api_key`）就以 cloud 為唯一來源，**唔會** fallback 去本地檔案。連唔到 cloud 就由 `load()` 直接拋 `DataCloudError`，由呼叫方決定點報俾 user：
  - `REQUEST_FAILED`：連唔到 cloud，`message` 會帶實際 URL
  - `INVALID_RESPONSE`：cloud 回應主體唔係合法 JSON
  - 其他 `code`：cloud 回 4xx/5xx，睇 `status_code`

```python
from rqark_app.cloud.client import DataCloudError

try:
    await config_mgr.load()
except DataCloudError as error:
    print(f'載入設定失敗: {error.message} ({error.code})')
```

##### Agent Defaults
每個用戶每個 `source`（同 `sessions.source` 同一套值）可以有一個默認 Agent，雲端存住，跨 client 共用。

- 開 `ConfigManager` 時傳 `source`，`load()` 就會順手讀返嗰個 source 嘅默認 Agent 落 `default_agent`（冇設過、或者指向已經唔存在嘅 Agent 都係 `None`）
- 本地檔案模式（cloud 未啟用）或者冇傳 `source` 都唔會發請求
- `set_default_agent(agent)` 同 `clear_default_agent()` 寫返上雲端；`agent` 一定要係 cloud 嚟嘅（本地 agent 冇 id，會拋 `ValueError`）

```python
from pathlib import Path

from rqark_app.agent.manager import AgentManager
from rqark_app.config.manager import ConfigManager

config_mgr = ConfigManager(str(Path.home() / '.rqark'), source='TUI')
await config_mgr.load()
agent_mgr = AgentManager(config_mgr.agents, config_mgr.default_agent)
```

### Agent App
#### Event
細化 core 嘅 `on_chunk`，將 `Chunk.type` 拆成獨立事件。

| 裝飾器 | 事件內容 |
|---|---|
| `on_think` | `AgentPayload[Chunk]`（`Chunk.type`：`reasoning_content`） |
| `on_content` | `AgentPayload[Chunk]`（`Chunk.type`：`content`） |
| `on_tool_calls` | `AgentPayload[Chunk]`（`Chunk.type`：`tool_calls`，`content` 為 list） |
| `on_tool_result` | `AgentPayload[ToolMessage]`（已由 `Chunk` 拆出） |
| `on_error` | `AgentPayload[Chunk]`（`Chunk.type`：`error`） |
| `on_message` | `AgentPayload[Message]`（user / tool / assistant / system） |
| `on_plan` | `AgentPayload[list[PlanItem]]` |
| `on_provider_switched` | `AgentPayload[ProviderSwitch]`（`old` / `new`） |

`Chunk.type` 為 `usage` 者唔會 emit。

#### Chat ReTry Loop
`AgentApp.chat` 係唯一入口。遇 `APIError` 或 context overflow 會無限重試：自動壓縮 context、輪換 Provider，直至成功回應。

## Example
```python
from rqark_core.types.provider import Provider
from rqark_app.app import AgentApp
from rqark_app.agent.agents import Wednesday

provider = Provider('MODEL_NAME', 'api_key', 'http://127.0.0.1:8080')
app = AgentApp([provider])


async def main():
    await app.chat('你係邊個?', Wednesday())


if __name__ == '__main__':
    asyncio.run(main())
```