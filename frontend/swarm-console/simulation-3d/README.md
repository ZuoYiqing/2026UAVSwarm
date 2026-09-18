# UAVSwarm Simulation 3D

独立的 CesiumJS 三维仿真子应用。当前默认场景是完全离线的虚构青岚市，范围为
3.6 km × 2.8 km，包含商务楼群、住宅街区、河道、桥梁、高架及匝道、体育场、公园、山地森林，
以及原点附近的无人系统园区、机库、跑道和停机坪。页面中的载具由统一快照接口动态创建和删除，
不是写死为固定的三架无人机。

## 当前能力

- CesiumJS `1.143.0`，可在无公网环境运行；
- 默认青岚市，保留独立任务园区与 3D Tiles 1.1/1.0 兼容性样例；
- 城市、园区、商务区、滨河立交、山地五个视点，独立建筑、交通、绿植与标注图层；
- 可选阴影，窄屏场景/遥测面板，缩放与朝北操作；
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

本次独立分支开发时，先进入对应工作树，而不是主仓库目录：

```powershell
cd D:\2026UAVSwarm-worktrees\simulation-3d-cityscape\frontend\swarm-console\simulation-3d
```

再执行上面的安装和启动命令。合并后仍使用主仓库目录；不要同时在相同端口启动两份服务。

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
npm run test:browser
```

浏览器测试默认使用 Windows 已安装的 Edge；其他平台需要先执行
`npx playwright install chromium`。可用 `PLAYWRIGHT_CHANNEL` 环境变量指定本机浏览器通道。
测试自动使用 5189 端口并在结束后停止服务，截图存入已忽略的 `test-results/`。
测试覆盖桌面/窄屏画布像素、视点、图层、载具选择、DEMO/LIVE 切换与 Bridge stale 冻结恢复。
Bridge/API 测试使用契约夹具，不等同于真实 Runtime、PX4 或 Gazebo 联调。

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

它们位于 `public/tiles/`，仅用于验证 3D Tiles 1.1 和 1.0 加载能力。
默认城市没有下载地图、纹理或建筑数据，不需要 Cesium ion Token 或公网 CDN。
`src/city-layout.js` 定义可重复生成的布局与视点，`src/city-geometry.js` 使用 Three.js
构建几何并按图层/材质合批，`src/city-scene.js` 将其交给 Cesium Primitive 渲染。
只有 Cesium 管理相机和画布，不存在第二套叠加的 Three.js 渲染器。
原有独立园区仍由 `src/campus-scene.js` 构建。生产环境按离线部署文档打包 `dist/` 即可。

## 坐标约定

任务区内部统一使用 ENU：

- X：East；
- Y：North；
- Z：Up。

数据层也接受 NED 和 WGS84。NED 会在 `src/vehicle-contract.js` 中转换为 ENU：
`east = y`、`north = x`、`up = -z`。

城市保持既有 ENU 原点（经度 116.3913、纬度 39.9075、高度 0），并非该真实位置的测绘地图。
建筑、桥面和山体是展示几何，不会自动成为 Gazebo 碰撞体、飞行规划障碍物或 Cesium 地形高度服务。
LIVE 载具坐标不做道路吸附或山体抬高；真实环境的坐标、地形与碰撞必须由仿真/Runtime 工作线确认。
本次不新增演示载具，也不把前端 DEMO 数据混入 LIVE。
