# Demo Runbook (v0.1 Baseline)

本 runbook 仅用于演示当前最小闭环：

`submit-mission / submit-action -> runtime -> policy_decision_event -> fake adapter -> action_result -> audit -> replay`

## 1) 环境
```bash
pip install -e .[dev]
```

## 2) 路径 A：正常通过（ALLOW）
```bash
python -m uav_runtime.console.cli submit-action hover --mission-id demo-a --risk-hint 1 --pretty
```
预期：
- `status: accepted`
- `accepted: true`

## 3) 路径 B：策略拒绝（DENY）
```bash
python -m uav_runtime.console.cli submit-action goto --mission-id demo-b --risk-hint 5 --demo-link-state lost --pretty
```
预期：
- `status: blocked`
- `accepted: false`
- `code: REASON_CODE_RISK_LEVEL_EXCEEDED`

## 4) 路径 C：等待确认（REQUIRE_CONFIRM）
```bash
python -m uav_runtime.console.cli submit-action goto --mission-id demo-c --require-confirm --pretty
```
预期：
- `status: waiting_confirmation`
- `accepted: false`
- `code: REASON_CODE_CONFIRMATION_REQUIRED`

## 5) 回放最近审计
```bash
python -m uav_runtime.console.cli replay-last --pretty
```

## 6) 最小验证
```bash
python -m pytest tests/integration/test_minimal_runtime_flow.py -q
python -m pytest tests/test_cli.py -q
python -m pytest -q
```
