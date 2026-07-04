# 2026UAVSwarm Demo Shell（录屏演示模式）

## 用途
这是一个用于**领导汇报 / 评审录屏**的轻量单页演示壳，核心展示链路：

`mission/action -> policy_decision_event -> adapter -> action_result -> replay`

> 说明：该页面用于演示控制面逻辑与状态流转，不等同于正式产品前端；当前不连接真实 PX4/MAVLink/SITL 后端。

## 快速运行
```bash
python -m http.server 8000
```

浏览器打开：`http://localhost:8000/demo/`

## 离线验证（重点）
1. 先**断开网络**（关闭 Wi-Fi / 拔网线）。
2. 在仓库根目录运行：`python -m http.server 8000`。
3. 访问：`http://localhost:8000/demo/`。
4. 在浏览器执行强制刷新：`Ctrl + F5`。
5. 打开 DevTools → Network：
   - 确认没有外部 `https://` 资源请求；
   - 仅有本地 `demo/index.html`、`demo/styles.css`、`demo/app.js` 等请求。
6. 手动验证四个场景与自动轮播：
   - 正常放行（ALLOW）
   - 高风险拒绝（DENY）
   - 等待确认（REQUIRE_CONFIRM）
   - 接入位预留（SITL_WIRING）
   - 自动演示（Auto Demo / Play All）

## 常见问题排查（空白页）
- 先按 `Ctrl + F5` 强制刷新，避免浏览器命中旧缓存。
- 打开 DevTools Console，确认没有脚本语法报错。
- 当前 `demo/app.js` 为纯本地原生 JS（不依赖 React/CDN），如果仍空白，请确认加载的是仓库最新文件而不是旧缓存副本。

## 演示重点（中文主叙述）
- 顶部总览条：场景 / 任务 / 动作 / 适配器 / 后端 / 系统状态；
- 四个核心场景：
  1. 正常放行（ALLOW）
  2. 高风险拒绝（DENY）
  3. 等待确认（REQUIRE_CONFIRM）
  4. 接入位预留（SITL_WIRING）
- 时间线展示：从 mission_request 到 replay 的全链路事件可回放。

## 推荐录屏顺序（2~3 分钟）
1. 正常放行（ALLOW）
2. 高风险拒绝（DENY）
3. 等待确认（REQUIRE_CONFIRM）
4. 接入位预留（SITL_WIRING）
5. 自动演示（Auto Demo / Play All）作为收尾

详细讲稿请见：`docs/demo_video_script.md`
