# Demo Video Script (2~3 min, leadership briefing)

## 录制目标
用 2~3 分钟清楚讲明：
1) 控制面闭环已打通；
2) 策略裁决与执行面解耦；
3) SITL backend 接入路径已准备。

## 录制前准备
1. 启动：`python -m http.server 8000`
2. 打开：`http://localhost:8000/demo/`
3. 全屏录制（建议 1080p, 30fps）。

---

## 推荐讲解顺序

### 00:00 - 00:25 平台总览条
- 展示顶部：Scene / Mission / Action / Adapter / Backend / System Status。
- 讲解：
  - “这是演示壳，不是正式 GUI。”
  - “目标是展示控制面链路与执行面状态。”

### 00:25 - 00:55 ALLOW（正常放行）
- 点击 `ALLOW`。
- 指给观众看：
  - 地图：目标点激活、航迹高亮、无人机上浮/移动；
  - 卡片：`decision_code=allow`、`result.code=exec_ok`；
  - 时间线：逐步高亮到 replay。

### 00:55 - 01:25 DENY（高风险拒绝）
- 点击 `DENY`。
- 指给观众看：
  - 地图：风险区红色增强、无人机不动、目标锁定；
  - 卡片：`decision_code=deny`、`primary_reason_code=REASON_CODE_RISK_LEVEL_EXCEEDED`；
  - 结果：adapter skipped。

### 01:25 - 01:55 REQUIRE_CONFIRM（等待确认）
- 点击 `REQUIRE_CONFIRM`。
- 指给观众看：
  - 地图：黄色等待提示与暂停状态；
  - 卡片：`decision_code=REQUIRE_CONFIRM`、`status=waiting_confirmation`。

### 01:55 - 02:25 SITL_WIRING（接入位预留）
- 点击 `SITL_WIRING`。
- 指给观众看：
  - 地图：SITL 提示条与虚线路径；
  - 卡片：`adapter=mavlink`、`backend_mode=sitl`、`code=smoke_not_connected`；
  - 文案：`SITL backend path prepared; real backend not connected`。

### 02:25 - 02:50 Auto Demo
- 点击 `Auto Demo / Play All`，自动轮播四场景。
- 结尾话术：
  - “当前可用于汇报演示；后续在不改控制面 contract 的前提下替换真实 backend。”

---

## 录制注意事项
- 每个场景停留 6~8 秒，给观众阅读时间。
- 避免说“真实飞控已接通”；统一表述“backend path prepared / pending connection”。
