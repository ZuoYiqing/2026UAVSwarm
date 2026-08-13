# UAVSwarm Simulation 3D

独立的 CesiumJS 三维仿真子应用。当前默认场景是完全离线的任务园区，包含建筑群、机库、
跑道、停机坪、道路、绿地、能源设施和边界。页面中的载具由统一快照接口动态创建和删除，
不是写死为固定的三架无人机。

## 当前能力

- CesiumJS `1.143.0`，可在无公网环境运行；
- 默认任务园区，以及 3D Tiles 1.1/1.0 兼容性样例；
- 多旋翼、固定翼、垂直起降固定翼、无人车等混合平台；
- 根据完整状态快照动态增删载具、更新姿态、位置、遥测和 Agent 状态；
- 默认 LIVE，独立打开时轮询 Runtime `GET /api/vehicle-snapshot`；
- 本地两分钟演示只在点击 `DEMO` 或使用 `?mode=demo` 时启用；
- iframe `postMessage` 和同窗口 JavaScript Bridge 两种集成方式。

页面中的 `02:00` 不是视频，也不是 Gazebo/PX4 飞行脚本。它只是浏览器内生成的本地测试
数据，用于显式 DEMO 模式下验证渲染、轨迹、选择和跟随。LIVE 数据超时后会保留并冻结
最后位置，同时标记 `STALE`，不会继续生成假运动。

## 开发运行

```powershell
cd D:\2026UAVSwarm\frontend\swarm-console\simulation-3d
npm ci
npm run dev
```

浏览器打开：

```text
http://127.0.0.1:5179/
```

开发服务器会把同源 `/api/*` 代理到 `http://127.0.0.1:8765/api/*`。因此独立 LIVE 模式
需要另一个终端启动 Runtime；Runtime 未启动时页面会明确显示断线，不会自动降级为 DEMO。

显式打开本地演示：

```text
http://127.0.0.1:5179/?mode=demo
```

前台运行时按 `Ctrl+C` 停止。后台脚本必须在本目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-dev.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\stop-dev.ps1
```

若当前终端位于 `C:\Users\m1360`，应先 `cd` 到上面的项目目录，或者给 `-File` 传绝对路径。

## 验证

```powershell
npm test
npm run build
```

## 数据接入

集成优先级只有一条：嵌入主控制台时由主控制台统一获取快照并通过 `postMessage` 发送；仅在
三维页面顶层独立打开时轮询 Runtime。父页面或 Bridge 快照一旦取得权威，Runtime 轮询会停止。

默认 Runtime API Base 是 `/api`，独立调试其他地址时可使用：

```text
?runtimeApiBaseUrl=http://127.0.0.1:8765/api
```

跨源地址要求 Runtime 明确允许当前页面 Origin；推荐仍使用 Vite/Nginx 同源代理。

- 人类可读契约：[docs/VEHICLE_FEED_CONTRACT_ZH-CN.md](docs/VEHICLE_FEED_CONTRACT_ZH-CN.md)
- JSON Schema：[public/contracts/vehicle-snapshot.schema.json](public/contracts/vehicle-snapshot.schema.json)
- 其他工作线提示词：[docs/CROSS_WORKSTREAM_PROMPTS_ZH-CN.md](docs/CROSS_WORKSTREAM_PROMPTS_ZH-CN.md)
- 完整离线部署：[docs/OFFLINE_DEPLOYMENT_ZH-CN.md](docs/OFFLINE_DEPLOYMENT_ZH-CN.md)

## 示例数据来源

用户下载的原始文件：

```text
C:\Users\m1360\Downloads\3d-tiles-samples-main.zip
```

项目只从中提取了：

```text
1.1/MetadataGranularities
1.0/TilesetWithDiscreteLOD
```

它们位于 `public/tiles/`，仅用于验证 3D Tiles 1.1 和 1.0 加载能力。默认园区由
`src/campus-scene.js` 本地构建，没有另外下载地图或建筑数据。

## 坐标约定

任务区内部统一使用 ENU：

- X：East；
- Y：North；
- Z：Up。

数据层也接受 NED 和 WGS84。NED 会在 `src/vehicle-contract.js` 中转换为 ENU：
`east = y`、`north = x`、`up = -z`。
