# Demo Video Script (≈2 minutes)

## 目标
- 录制一个 1~3 分钟、可放 PPT 的项目能力演示短视频。
- 强调当前已具备的控制面能力与事件链路，而非伪装真实仿真接入。

## 录制前准备
1. 启动本地静态服务：
   - `python -m http.server 8000`
2. 打开页面：
   - `http://localhost:8000/demo/`
3. 浏览器进入全屏，分辨率建议 1920x1080。
4. 录屏工具建议 30fps，开启鼠标高亮。

## 演示顺序与讲解词

### 第 1 段（约 25s）：总览
- 操作：展示页面整体布局（左态势、右控制区、底部时间线）。
- 讲解：
  - “这个是 demo shell，不是正式前端。”
  - “核心展示链路是 action_request 到 policy 决策，再到 adapter 与结果回放。”

### 第 2 段（约 35s）：ALLOW 场景
- 操作：点击 `ALLOW`。
- 重点看：
  - `decision_code=allow`
  - `status=accepted`
  - 无人机出现起飞/悬停变化。
- 讲解：
  - “这表示在当前策略下动作被允许，执行路径贯通，结果进入 replay 摘要。”

### 第 3 段（约 30s）：DENY 场景
- 操作：点击 `DENY`。
- 重点看：
  - `decision_code=deny`
  - `primary_reason_code=REASON_CODE_RISK_LEVEL_EXCEEDED`
  - adapter 显示未执行。
- 讲解：
  - “策略拒绝发生在执行前，体现控制面和执行面的边界。”

### 第 4 段（约 30s）：REQUIRE_CONFIRM 场景
- 操作：点击 `REQUIRE_CONFIRM`。
- 重点看：
  - `decision_code=REQUIRE_CONFIRM`
  - `status=waiting_confirmation`
  - 时间线体现 pending 路径。
- 讲解：
  - “该场景展示确认门槛与可审计事件链，不直接下发执行。”

### 第 5 段（约 20s）：收口
- 操作：快速切回 `ALLOW`，展示 3 场景切换流畅性。
- 讲解：
  - “当前壳层可支持领导汇报与录屏；后续可平滑接入真实 backend，而不改控制面 contract。”

## 录制建议
- 单次控制在 1:50~2:20。
- 鼠标移动慢、每次停留 2~3 秒，保证字幕/讲解同步。
- 不要演示任何“真实 PX4 已接通”表述，避免误导。
