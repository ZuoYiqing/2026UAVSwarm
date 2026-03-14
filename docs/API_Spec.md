# 产品接口报告（API 规范）- SwarmAI Platform

版本：v0.1（Demo）

## 1. 总览

本平台对外提供 REST API（FastAPI），用于前端/第三方系统集成。

- Base URL: `http://<host>:<port>`
- Swagger: `/docs`

## 2. 通用约定

- 编码：UTF-8
- 数据格式：JSON
- 错误返回：HTTP 4xx/5xx + JSON

## 3. 接口列表

### 3.1 健康检查

**GET** `/health`

响应：
```json
{"status": "ok"}
```

### 3.2 生成计划（决策 + 协议 + 代码骨架）

**POST** `/v1/plan`

请求：
```json
{
  "mission": { ... },
  "scene": { ... },
  "out_dir": "generated/api"
}
```

响应：
```json
{
  "decision": { ... },
  "protocol": { ... },
  "notes": "...",
  "artifacts_dir": "generated/api"
}
```

说明：服务端会在 `artifacts_dir` 下写入 `decision.json`, `protocol.json`, `codegen/`。

### 3.3 运行仿真评测

**POST** `/v1/sim/run`

请求：
```json
{
  "mission": { ... },
  "scene": { ... },
  "decision": { ... }
}
```

响应：
```json
{
  "coverage_ratio": 0.73,
  "drop_rate": 0.11,
  "first_target_report_time_s": 24,
  "first_gs_action_time_s": 26,
  "message_stats": {
    "UAV_STATUS": {"sent": 360, "delivered": 320, "dropped": 40, "bytes_sent": 23040},
    "TARGET_REPORT": ...
  }
}
```

## 4. 鉴权/权限（建议，Demo 未实现）

- API Key / JWT
- RBAC：管理员/开发者/只读
- 审计：记录每次调用输入输出与生成版本
