# 2026UAVSwarm Console Frontend

这是一个独立于 `src/uav_runtime/` 的前端原型，用于展示无人机集群三维数字孪生运行平台。

当前版本是零依赖静态 SPA，方便快速预览和避免影响 Python runtime。后续可以在该目录内迁移到 Vite + React + TypeScript + CesiumJS，不需要改动现有 runtime 包。

## 运行

在仓库根目录执行：

```bash
python -m http.server 5178 --directory frontend/swarm-console
```

打开：

```text
http://localhost:5178/
```

## 页面

- 总览驾驶舱
- 任务规划
- 三维集群态势
- 单机详情
- Agent Runtime
- Policy Gate
- Skills 能力库
- Adapter / Backend
- 仿真中心
- 硬件资产
- Audit / Replay
- 模型与知识
- 系统设置

## 后续接入点

- `app.js` 中的 `state` 和 mock 数据可替换为 REST/WebSocket API。
- 三维态势区域当前是 CSS/SVG 原型，后续可替换为 CesiumJS Viewer。
- `Policy Gate`、`Adapter / Backend`、`Audit / Replay` 页面字段按当前 Python runtime 的 contract 设计。
