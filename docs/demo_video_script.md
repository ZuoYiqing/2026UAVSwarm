# Demo Video Script (1.5 ~ 3 minutes, leadership-ready)

## 目标
- 在 2 分钟左右清楚展示当前项目已具备的核心能力链路：
  `mission/action -> policy_decision_event -> adapter -> action_result -> replay`。
- 强调“已有能力与可扩展路径”，避免误导为“真实 PX4 已接通”。

## 录制前准备
1. 仓库根目录执行：`python -m http.server 8000`
2. 打开：`http://localhost:8000/demo/`
3. 全屏（推荐 1920x1080），录屏 30fps。
4. 页面默认进入 ALLOW 场景，可直接开始讲解。

---

## 演示顺序（可直接照念）

### 0:00 - 0:20 顶部总览
**操作**：停留在顶部栏 5~8 秒。  
**讲解词**：
- “这是 2026UAVSwarm 的 Demo Shell，不是正式产品 GUI。”
- “顶部实时显示当前场景、Adapter、Backend Mode、系统状态，便于快速理解系统处于哪条链路。”

### 0:20 - 0:45 场景 A：ALLOW
**操作**：点击 `ALLOW`。  
**观察点**：
- 地图：无人机起飞/移动，航迹线正常；
- 右侧：`decision_code=allow`，`result.code=exec_ok`；
- 时间线：按 mission_request → replay 逐步高亮。
**讲解词**：
- “这是正常放行路径：策略允许，执行层返回 accepted，回放摘要可追踪。”

### 0:45 - 1:10 场景 B：DENY
**操作**：点击 `DENY`。  
**观察点**：
- 地图：禁飞/风险区高亮，无人机保持不动；
- 右侧：`decision_code=deny`，主因 `REASON_CODE_RISK_LEVEL_EXCEEDED`；
- 结果：adapter 被跳过。
**讲解词**：
- “拒绝发生在执行前，体现控制面与执行面边界。”

### 1:10 - 1:35 场景 C：REQUIRE_CONFIRM
**操作**：点击 `REQUIRE_CONFIRM`。  
**观察点**：
- 地图：无人机呈等待/闪烁状态；
- 右侧：`decision_code=REQUIRE_CONFIRM`，`status=waiting_confirmation`；
- 时间线显示 pending 路径。
**讲解词**：
- “这条路径展示确认门槛，系统进入等待确认而非直接执行。”

### 1:35 - 2:00 场景 D：SITL_WIRING
**操作**：点击 `SITL_WIRING`。  
**观察点**：
- 地图底部提示：`SITL backend path prepared`；
- 右侧关键字段：`adapter=mavlink`，`backend_mode=sitl`，`code=smoke_not_connected`（或 sitl_not_configured）；
- 时间线完整到 replay。
**讲解词**：
- “这里不是没做，而是后端接入位已打通到 seam；当前真实 backend 尚未连接。”

### 2:00 - 2:20 Auto Demo 一键播放
**操作**：点击 `Auto Demo / Play All`，等待自动轮播 ALLOW→DENY→REQUIRE_CONFIRM→SITL_WIRING。  
**讲解词**：
- “自动演示模式可直接用于快速录屏和汇报复现。”

---

## 录屏质量建议
- 单段录制控制在 1:50 ~ 2:30。
- 鼠标动作慢、每次切换停留 3~5 秒。
- 避免“真实飞控已接通”措辞，统一说“backend path prepared / pending connection”。
