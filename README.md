# rqark-app
- 封裝 rqark-core
- 整合雲端服務（rqark-data-center / rqark-agent-cloud

- 提供功能
    - session 管理
        - opencc 簡轉繁
        - 生成 title
    - config 管理
        - provider 管理
        - agent 管理
    - 細化 on_event, on_message
- 另提供 libs RQArkDataCenterClient，用於登入 rqark-data-center，

同步 session 和 config 到雲端
    - RQARK_DATA_CENTER_URL
    - RQARK_DATA_CENTER_TOKEN