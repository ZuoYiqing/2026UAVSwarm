# 2026-09-16 阶段版本冻结

按用户要求停止继续排查与新增飞行测试，固定当前开发版本，后续在整个项目验证时继续处理。
这是 Draft 检查点，不是三机巡检或 G1 集成验收通过版本，不可合并。

## 版本和范围

- 分支：`codex/px4-gazebo-runtime-integration`，基线 `b4e2f6e`。
- 执行 checkout：`D:/2026UAVSwarm-worktrees/px4-gazebo-runtime-integration`，WSL 使用其 `/mnt/d/` 映射。
- PX4：`171f0f38cffa95f28d5e159f7aaf7599756f9e0e`，Gazebo 8.14.0，pymavlink 2.4.49。
- Runtime `3fa42eb`、控制台 `a20d658` 仅用于依赖检查/启动准备，无源代码修改。
- `config/vehicles.sitl.json` 未修改；scene 保留旧 `frame=local_ned` 兼容读取，同时显式标注 `public_frame=scene_ned` 和 map version。

## 已有证据

- 相关单元回归 75 项通过；Python AST 语法检查通过。
- 三机逐机隔离 ARM/TAKEOFF/LAND 真实回归 PASS。
- 首次三机巡检完成全部航点和落地解锁，ACK 接受；最大相对起飞高度约 8.185/10.240/12.274 m。
  遥测最小距离 7.915 m，Gazebo 实测最小距离 7.934 m；动态坐标残差失败，整体仍为 FAIL。
- 后续诊断保留配对样本，观察到局部位置与世界位置约 1.56 m 的动态偏差，以及 uORB listener 3 秒超时导致标定失效。
  失败均保留，飞行恢复报告确认三机 landed/disarmed。
- 无 MAVLink receiver 的静态原点采样成功；它不证明动态方向/误差通过。
- integrated health 在 Runtime evidence 缺失时真实输出 simulation_status=ready、system_status=unknown、ready=false。
- G1 主控制台 UAV-02 正式起飞/保持/降落：未执行。准备启动后按用户要求冻结，没有发出集成飞行动作。

可审查的历史摘要：[`fixtures/runtime-integration-20260916.json`](fixtures/runtime-integration-20260916.json)。
原始报告在本 worktree `.runtime/px4_gazebo/validation/` 和 `patrol_motion_diagnostic3.json`，不提交运行日志。
历史 fixture 明确不是可发布的实时证据；不得改时间戳后重放。

## 待整个项目验证处理

1. 定位动态位姿偏差与采样对时/估计误差；不放宽 0.5 m 标定残差和 0.75 m 动态误差阈值来取得 PASS。
2. 处理 uORB listener 超时、启动后 health 偶发未就绪、恢复落地后 ARM 健康拒绝；先读明确失败证据，再复测。
3. Runtime 提供独立 heartbeat_timestamp、position_timestamp、run_id 和有效期文件/接口。
   当前接口的 snapshot 时间不能代替两类消息的新鲜度。
4. 确认 Runtime 证据接收按 source timestamp 处理过期；当前 publisher 扣减剩余 TTL，正式源时间判定仍由 Runtime 主责完成。
5. 完成 G1 UI → Runtime → UAV-02，证明 UAV-01/03 始终静止且 disarmed，再复测完整三机巡检。
6. 补齐暂停/低 RTF、world/model 异常的真实故障 fixture；当前相关分支已有单元测试，不冒充真实注入验收。
7. 上述完成后才开展青岚市小范围物理场景，当前不改变旧 world。

接口契约与操作见 [集成补充手册](PX4_GAZEBO_RUNTIME_INTEGRATION_ZH-CN.md)。

冻结收尾检查：最终 75 项单元测试通过（3.17 秒）；Python AST、shellcheck、git diff --check 通过。harness 安全停止后端口释放，重复停止返回无状态可停止；未观察到 Runtime/控制台监听残留。
