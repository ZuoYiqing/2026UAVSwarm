# 主控台：联合验收准备与无飞行验证（2026-10-29/30）

本记录只覆盖主控台本线。静态页面、单元 fixture、浏览器 DOM、真实网关/飞行验证分别记录，不将准备完成写成联合验收 PASS。

## 基线与职责

- 固定集成基线：fbdc3b2ec2e26d1ccf4f2f5dd4ea671ba10caa00。
- 已核验其包含 Runtime 876bb92、算法 735af74、主控台 fc98648。
- 本线独立分支：codex/frontend-autonomy-observation-acceptance。
- 源码变更仅在 frontend/swarm-console/，排除 simulation-3d/；不在 main 开发。
- 集成负责人是唯一动作发送者；本线不点击起飞/降落/Smoke/Backend Check，不发送平台任务、cancel、reconcile 或 heartbeat。
- Runtime 负责已标定公共视图、缓存融合及 UAV-02 preflight 转发。主控台不偏移坐标，不把 raw local_position 拼成 scene_ned，不开 MAVLink 接收器。

## 页面与启动

在本线 worktree 根目录启动的静态服务：

```powershell
python -u -m http.server 5178 --bind 127.0.0.1 --directory frontend/swarm-console
```

- 主控台：http://localhost:5178/ 或 http://127.0.0.1:5178/。
- 独立平台面板：导航 Agent Runtime → 平台任务与链路（只读）。
- 预期地面网关：http://127.0.0.1:8765/api；实际地址须由 Runtime/集成确认。
- localhost:5178 与 127.0.0.1:5178 均在当前 Runtime ALLOWED_ORIGINS 中，但浏览器存储按 origin 隔离。

静态服务提供页面，不说明网关、平台代理、模型或 PX4 已就绪。不能为展示而启动 fixture Runtime 冒充真实在线。

## 真实环境只读检查

2026-10-30 02:33:02 UTC（北京时间 10:33:02）的 CLI 结果：

```text
HEAD http://localhost:5178/ → HTTP/1.0 200 OK
Server: SimpleHTTP/0.6 Python/3.11.7
GET http://127.0.0.1:8765/api/health → curl (28), 2007 ms timeout
```

同期端口检查能看到 5178 静态服务及另一负责人提供的 5179 服务；未看到 8765/8766/8767/8872 的监听。本线没有启动或控制后三类服务，也没有启动/停止其他负责人的 5179。

结论仅为页面已提供、网关当时不可达。没有取得真实 UAV-02 的 task/status/events，没有现场断链恢复或飞行通过的证据。

## 浏览器存储与审批阻塞

2026-10-29 已打开 127.0.0.1:5178 并读取 DOM：平台观测 UNKNOWN、HTTP OFFLINE，飞行按钮禁用，没有伪造在线节点。

但该 origin 保留之前的 fixture API 地址 8876 及待核 pending 请求。通过页面尝试改成 8765 时，被“仍有请求在执行或等待核实”锁拒绝。保留记录、不删除、不清空 localStorage、不重发请求；不能把旧来源的未知结果静默抹掉。

准备从 localhost:5178 独立 origin 进行只读观测时：

- 2026-10-29：自动审批因额度限制未完成，导航没有执行。
- 2026-10-30 用户继续后重试：先遇到 webview attach 超时；恢复已创建的空白标签后，原来源导航被自动审批拒绝，理由为先前来源审批未解决，不能靠重复申请绕过。

此后停止该浏览器导航，不换浏览器、原始 CDP、隐藏脚本或其他 UI 机制绕过。未取得新的 localhost DOM 或截图，未声称旧浏览器已成功切换到真实网关。CLI 的 200 不能代替浏览器批准与界面截图。

## 已复现的旧动作路由缺口与最小补丁

固定基线的 actionPermission() 仅按旧 fleet、HTTP、观测和动作记录判断，没有检查已确认的平台执行归属。

条件：平台 status 已确认 node_id=UAV-02；但旧缓存/后续公共融合视图仍保留该节点的可用 legacy endpoint。此时基线对 TAKEOFF 仍返回 allowed=true，可能把操作者引向已 exclude 的旧地面动作路由。Runtime 服务端仍有拒绝防线；本问题不表示已发生实际重复飞行。

先补回归再运行，基线结果：

```text
platform-owned node cannot use legacy action or backend routes even with cached legacy endpoint
FAIL: true !== false
```

最小实现：

1. 以已确认的 platformObserver.state.status.node_id 判断平台归属。
2. 禁用该节点旧 TAKEOFF、Smoke、LAND、Backend Check 按钮；动作入口及 Backend Check 函数自身也拒绝，不只依靠 disabled 样式。
3. 平台状态 stale 时保留最后确认归属，不回退旧路由；切换 API 来源仍按原规则清理观察器。
4. 未配置平台代理的传统三机模式不凭空认定平台归属；UAV-01 的既有准入不被本补丁改变。
5. 不把旧 LAND 替换为平台 cancel，更不发送 DISARM；不新增动作路由。

这是执行入口准入收紧，没有修改飞行完成阈值、Policy、坐标契约或 Runtime 代码。

## 测试结果与边界

- npm run check：通过。
- npm test：136 passed，0 failed（原固定版 135；新增 1 项回归）。
- 新用例使用现有最小 DOM 桩与 fake fixture，只在内存记录调用；断言 UI 禁用、takeoff/land/smoke/backend POST 调用为零、平台 stale 后仍拒绝、UAV-01 原准入保留。
- 已有回归继续覆盖：legacy 排除 UAV-02 时平台仍可见；平台 503 保留任务；store_id/seq 补收和去重；boot 重启与换库区分；终态不能被旧 executing 覆盖；ACK 不等于遥测完成。

以上是前端单元/fixture 结果，不是实际平台、切链、ACK 或 LAND 的飞行证据。

## 联合窗口待核

已向 Runtime 与集成负责人协调，只做无飞行准备。Runtime 正在补公共 view fixture/生产者；集成负责人此前的人类任务仍限定只读历史调查，恢复后也在确认版本和窗口。

待明确 ready 后再由集成统一：

1. 确认固定新组合、唯一执行器、Runtime 网关及平台代理地址。
2. 授权并恢复浏览器来源，确保不误用旧 fixture 配置或删除未知 pending。
3. GET 观察真实 UAV-02 身份、任务状态、store_id、event_seq 和执行模式，保留同时窗 DOM/截图和后端日志。
4. 由集成发送唯一完整任务并统一故障注入；主控台只记录断链 stale/unknown、任务结论不被改写、恢复补事件和 POST 不重发证据。
5. 对平台缺失或 stale 的公共坐标明确显示未知，不在前端补偏移；ACK、完成证据、落地和上锁分别判断。

上述事项尚未执行。本记录不授权启动飞行或合并 main。

## Runtime 15889d1 公共视图静态复核及后续补丁（2026-10-30）

只读查阅固定提交 `15889d1d744e43edbb532819285c12cc616ac541` 的 `docs/platform_view_contract_v1.md`、`docs/fixtures/platform_view_v1.json`、`platform/view.py` 和 `platform/gateway.py`。本线仍以 fbdc3b2 + 87b2c08 为开发基线，没有合并 Runtime 或更改它的文件。

生产者源码表明：内部 `/api/platform/view` 不供浏览器直连；地面缓存融合至原 `/api/snapshot`、`/api/vehicle-snapshot`、`/api/telemetry/latest`、`/api/vehicles` 等公共 GET 路由，顶层新增 `platform_view`（包括 node_id、fresh、reason、age_ms、store_id、run_id）。源失联保留 UAV-02 和旧 pose 并标记 stale/不可用；位置和标定分别老化，公共 view 新鲜不表示位置或武装状态新鲜。坐标已由平台完成一次标定转换，主控台不再平移。

本线复现并修补两个消费侧问题：

1. 87b2c08 只认独立 platform/status 的归属。若公共视图先返回 UAV-02、status 尚不可用，旧 endpoint 可使旧动作准入返回 true。新增本 API 来源的归属缓存，接受原公共响应明确的 `platform_view` v1.0 node_id；即使该观测 stale，也保留独占归属并禁用旧动作及 Backend Check。切换来源清空缓存，丢弃旧来源迟到的状态响应；不把 fresh 当飞行许可。
2. 单机武装卡片原先对旧 `armed=false` 显示绿色 DISARMED，缺失值在汇总中计为 0。现在缺失或节点/地面观测过期时显示 UNKNOWN，可附最后上报值；详情、模块、Backend 及汇总使用一致语义。全部节点新鲜且 armed 布尔值齐全时，仍显示实际计数。

两项回归在修补前均失败，修补后通过。这是旧入口准入和证据展示的收紧，没有修改飞行完成阈值，也没有新增平台动作按钮或把 LAND 改为 cancel/DISARM。

固定生产者 JSON 逐字节复制到 `tests/fixtures/platform-view-v1.json`；其 `producer_projection_fixture_not_flight_evidence` 标记、1970 受控时钟和 map-fixture-1 均保留。它只是子集断言，单元用例的公共响应外壳、时间、store/run 等另行明确合成，没有注入浏览器。

新增 4 项回归覆盖：公共视图与 status 的到达次序/失联归属保留；武装 stale/缺失显示；换来源后旧响应丢弃；原样转发公共元数据与 raw y=2、scene y=10 的生产者坐标，位置不可用/标定过期仍保留旧 pose，HTTP/view 新鲜不洗掉 stale。

本轮 `npm run check` 通过；`npm test` **140 passed / 0 failed**（前次 136）。仅为无网络的前端 unit/fixture 检查。Runtime 报告的 995 passed / 12 skipped 及跨线 fixture 10 passed 未在本线独立重跑，不记为主控台或真实飞行 PASS。

仍有明确限制：原始 `state.vehicleSnapshot` 及 Bridge 保留顶层 platform_view；归一化 fleet 不展开这些字段，主控台 UI 尚未逐项展示公共视图 reason/age/store/run。独立平台面板继续使用原 task/events 命名空间和 store/seq，不拿公共快照覆盖任务结论。三维接收后的归一化及 UI 属于三维线，不由本补丁修改或证明。

本轮未启动任何静态/Runtime/模型/仿真服务、未发飞行动作、未重试被自动审批拒绝的浏览器来源，也没有取得新截图或真实完整公共响应。前文 10:33 的端口/页面探测仅是历史时点，不表示现在仍在线；三维线后续报告其 18:37 探测连接拒绝，属于对方观测，不冒充本线实测。真实同窗观测仍待集成确认版本与恢复窗口，并解决浏览器来源审批。
