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

## Example