new tool call_agent
用戶設定好曬佢可以call咩agent
同 SubAgent 作用差唔多，不過 Agent 會有自己的 Session 同 Tool + Prompt

## 星型
主 Agent + Sub Agent
- 所有協調經主 LLM：邊個做、做咩、結果點驗收，都係主 LLM 話事
- Sub 之間唔直接溝通，只對上報
- 代表：opencode task tool、Claude Code subagents
- 特性：context 隔離自然、權限易管（sub 權限繼承自父）、但要主 LLM 控制一切，主係 bottleneck 

## 網狀 
- 冇固定層級，任何一個可以直接同另一個傾（mailbox）、可以自己 claim 任務（shared task list）
- 代表：Claude Code Agent Teams
- 特性：適合需要互相 challenge、討論嘅工作；但要自己解決協調問題（誰 claim、誰等邊個、race condition）