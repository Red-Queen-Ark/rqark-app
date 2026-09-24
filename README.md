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

#### Agents Manager

#### Session Manager

#### Config Manager

### Agent App
#### Event

#### Chat ReTry Loop

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