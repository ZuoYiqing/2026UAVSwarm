# 测试计划（Test Plan）

版本：v0.1（Demo）

## 1. 测试范围

- 输入数据校验：mission/scene schema
- 决策生成：RulePlanner 输出 decision_schema 合法
- 协议生成：protocol_schema 合法
- 代码生成：messages.h/messages.py 生成成功
- 仿真闭环：能够完成目标上报->GS响应->簇内重分配

## 2. 用例

### TC-01：demo 闭环

步骤：
1. `python -m swarm_ai_platform.cli demo`
2. 检查 generated/ 目录产物

预期：
- decision.json, protocol.json, sim_report.json 存在
- sim_report 中 coverage_ratio 在合理范围（>0.5 作为 Demo 基线）

### TC-02：丢包压力

修改 examples/scene_demo.json 将 loss_rate 调到 0.3，重复 TC-01。

预期：
- 系统仍能产生 TARGET_REPORT/TARGET_SUMMARY/CMD_ACTION 消息闭环
- drop_rate 升高但系统不崩溃

### TC-03：schema 防线

故意删除 mission_json 的必填字段 mission_id，运行 plan。

预期：
- 报错并指出 schema 校验失败位置

## 3. 自动化建议

- GitHub Actions/内网 CI：对 demo、schema、codegen 做单元测试
- 每次协议变更触发仿真回归（golden metrics 比对）
