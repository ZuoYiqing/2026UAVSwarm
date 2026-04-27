# Demo 录屏讲稿（2~3 分钟，领导汇报版）

## 录制目标
用 2~3 分钟讲清三件事：
1. **控制面闭环已打通**（mission/action 到 replay 的链路完整可见）；
2. **策略裁决与执行面解耦**（policy 与 adapter/backend 分层清晰）；
3. **SITL 后端接入路径已预留**（当前为演示壳，不宣称真实飞控已接通）。

## 录制前准备
1. 启动静态服务：`python -m http.server 8000`
2. 打开页面：`http://localhost:8000/demo/`
3. 建议全屏录制：1080p / 30fps。

---

## 推荐讲解顺序（含话术）

### 00:00 - 00:25 顶部总览条（Overview）
- 指向顶部字段：
  - 场景（Scene）
  - 任务（Mission）
  - 动作（Action）
  - 适配器（Adapter）
  - 后端（Backend）
  - 系统状态（Status）
- 建议话术：
  - “这是演示壳（Demo Shell），不是最终业务 GUI。”
  - “重点是展示控制面链路与策略/执行状态闭环。”

### 00:25 - 00:55 正常放行（ALLOW）
- 点击：`正常放行（ALLOW）`
- 重点观察：
  - 地图：目标点激活、航迹高亮、无人机进入执行态；
  - 策略卡：`decision_code = allow`；
  - 结果卡：`result.code = exec_ok`；
  - 时间线：逐步点亮到 replay。
- 建议话术：
  - “该场景体现策略放行后，执行面 accepted，闭环贯通。”

### 00:55 - 01:25 高风险拒绝（DENY）
- 点击：`高风险拒绝（DENY）`
- 重点观察：
  - 地图：禁飞区告警增强，目标锁定，无人机保持；
  - 策略卡：`decision_code = deny`；
  - 原因：`REASON_CODE_RISK_LEVEL_EXCEEDED`；
  - 结果：`adapter = skipped`（执行层未下发）。
- 建议话术：
  - “风险超限在策略层被阻断，避免危险动作进入执行面。”

### 01:25 - 01:55 等待确认（REQUIRE_CONFIRM）
- 点击：`等待确认（REQUIRE_CONFIRM）`
- 重点观察：
  - 地图：等待确认提示条；
  - 策略卡：`decision_code = REQUIRE_CONFIRM`；
  - 结果卡：`status = waiting_confirmation`。
- 建议话术：
  - “命中人工确认规则后，系统暂停并保留可追踪状态。”

### 01:55 - 02:25 接入位预留（SITL_WIRING）
- 点击：`接入位预留（SITL_WIRING）`
- 重点观察：
  - 地图：SITL 提示与虚线路径；
  - 结果卡：`adapter = mavlink`、`backend_mode = sitl`、`code = smoke_not_connected`。
- 建议话术：
  - “路径已到后端接入位；当前真实后端尚未连接，这是预期演示状态。”

### 02:25 - 02:50 自动演示（Auto Demo / Play All）
- 点击：`自动演示（Auto Demo / Play All）`，自动轮播四个场景。
- 结尾话术：
  - “当前版本可用于汇报演示与评审。”
  - “后续在不改控制面 contract 的前提下替换真实 backend。”

---

## 录制注意事项
- 每个场景建议停留 6~8 秒，便于观众阅读关键字段。
- 禁止表述“已接通真实飞控”；统一表述为：
  - “后端接入路径已预留（prepared）”；
  - “真实后端待连接（pending connection）”。
