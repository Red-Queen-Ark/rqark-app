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
管理 Agent 序列，提供當前 Agent 讀取 (`agent`) 同手動切換 (`switch_to`)。

#### Session Manager
- 管理對話 Session，可選配 `SessionStorage` 持久化
- 內建 `JSONLStorage`，每個 Session 存成一個 `.jsonl`（首行 metadata，之後每行一個訊息）。

#### Config Manager
- 由設定目錄載入 agents 同 providers，透過 prompts/tools 註冊表建構物件，未設定時用內建預設
- `DirCache` 另外記錄每個工作目錄對應嘅 session ids。

### Agent App
#### Event
將 core 嘅 `AgentPayload` 細化成 8 種具型別事件：`think`、`content`、`tool_calls`、`tool_result`、`error`、`message`、`plan`、`provider_switched`，以 decorator 形式註冊 callback。

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