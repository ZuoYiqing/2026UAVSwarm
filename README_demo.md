# 2026UAVSwarm Demo Shell (Presentation Mode)

## 这是什么
这是一个**录屏优先**的轻量展示壳（single-page demo），用于向领导/评审快速演示当前项目能力：

`mission/action -> policy_decision_event -> adapter -> action_result -> replay`

> 注意：这不是正式产品前端，也不是实时 PX4/MAVLink 接入界面。

## 快速运行
在仓库根目录执行：

```bash
python -m http.server 8000
```

浏览器打开：

- `http://localhost:8000/demo/`

## 内置 4 个场景
- **ALLOW**：正常放行（accepted）
- **DENY**：高风险拒绝（blocked）
- **REQUIRE_CONFIRM**：等待确认（waiting_confirmation）
- **SITL_WIRING**：`adapter=mavlink` + `backend_mode=sitl`，展示后端接入位已准备但未连接

## 录屏功能
- 支持 **Auto Demo / Play All** 自动轮播：
  `ALLOW -> DENY -> REQUIRE_CONFIRM -> SITL_WIRING`
- 场景切换时会同步更新：
  - 左侧二维态势（无人机、航迹、目标、风险区）
  - 右侧决策与结果卡片
  - 底部事件时间线（带逐步高亮）

## 推荐录制脚本
请直接参考：

- `docs/demo_video_script.md`
