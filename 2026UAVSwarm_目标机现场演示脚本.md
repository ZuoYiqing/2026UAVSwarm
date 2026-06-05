# 2026UAVSwarm 目标机现场演示脚本

## 适用前提
- 目标机系统：Windows
- 使用终端：PowerShell
- 离线完整环境路径：`D:\offline_envs\airsim_agent`
- 项目代码路径：`D:\2026UAVSwarm`
- 项目当前状态：全量 `pytest` 已通过
- 当前演示重点：**控制面协议、policy gate、runtime 主链路、adapter gateway、audit / replay**

---

## 一、演示目标

本次演示不是展示真实无人机飞行，而是展示：

1. 这个项目已经形成一个 **UAV-Agent Runtime v0.1 基线**
2. 它不是聊天脚本，而是一个具备：
   - 控制面协议
   - policy gate
   - runtime
   - adapter gateway
   - audit / replay
   的最小内核
3. 当前已经通过测试锁定行为边界
4. 下一步可以在**不改控制面协议**的前提下继续接 fake adapter / PX4 SITL / MAVLink

---

## 二、PowerShell 现场演示命令（推荐顺序）

### 第 0 步：允许当前会话执行脚本
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

### 第 1 步：激活离线完整环境
```powershell
D:\offline_envs\airsim_agent\Scripts\Activate.ps1
conda-unpack
```

### 第 2 步：确认 Python 环境
```powershell
python -V
where python
```

### 第 3 步：进入项目目录
```powershell
cd D:\2026UAVSwarm
```

### 第 4 步：先证明基线可用（推荐）
```powershell
python -m pytest tests\unit\test_protocol_schema.py -q
python -m pytest tests\unit\test_policy_contract_shapes.py -q
python -m pytest tests\integration\test_minimal_runtime_flow.py -q
python -m pytest -q
```

### 第 5 步：设置源码路径
```powershell
$env:PYTHONPATH = "$PWD\src"
```

### 第 6 步：展示 CLI 总入口
```powershell
python -m uav_runtime.console.cli --help
```

### 第 7 步：展示可用命令
```powershell
python -m uav_runtime.console.cli submit-mission --help
python -m uav_runtime.console.cli submit-action --help
python -m uav_runtime.console.cli show-status --help
python -m uav_runtime.console.cli show-audit --help
python -m uav_runtime.console.cli replay-last --help
```

### 第 8 步：展示当前系统状态
```powershell
python -m uav_runtime.console.cli show-status
```

### 第 9 步：展示审计记录
```powershell
python -m uav_runtime.console.cli show-audit
```

### 第 10 步：展示最近一次回放
```powershell
python -m uav_runtime.console.cli replay-last
```

### 第 11 步：收尾（可选，再次证明基线稳定）
```powershell
python -m pytest -q
```

---

## 三、最短可复制命令版

如果现场时间很短，可以直接按下面顺序执行：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
D:\offline_envs\airsim_agent\Scripts\Activate.ps1
conda-unpack
cd D:\2026UAVSwarm
python -m pytest -q
$env:PYTHONPATH = "$PWD\src"
python -m uav_runtime.console.cli --help
python -m uav_runtime.console.cli show-status
python -m uav_runtime.console.cli show-audit
python -m uav_runtime.console.cli replay-last
```

---

## 四、每一步建议怎么讲

### 第 0～2 步：环境激活
建议讲：
> 这一步是在目标机上激活离线迁移过来的完整环境。  
> 这说明项目可以脱离开发机，在无网条件下独立运行。  
> `conda-unpack` 用于修正环境解压后的路径引用。

### 第 3～4 步：测试证明基线
建议讲：
> 我先不直接讲概念，而是先用测试证明当前 baseline 已经冻结。  
> 这里分别覆盖了协议 schema、policy contract 和最小 runtime flow。  
> 最后跑全量 pytest，说明当前 skeleton、contract、tests 已经对齐。

### 第 5～7 步：CLI 入口
建议讲：
> 当前阶段没有做 GUI，而是保留一个最小 CLI，目的是先把控制面和执行链路跑通。  
> CLI 入口服务于 demo，不追求大而全，而追求稳定、可复现。

### 第 8 步：系统状态
建议讲：
> 这里展示的是当前 runtime 的状态入口。  
> 当前系统不是只会执行命令，而是已经具备运行时语义。

### 第 9 步：审计
建议讲：
> 所有动作都不是直接穿透到底层执行，而是先经过 policy gate，并形成 audit 记录。  
> 这使后续回放、解释、排障与专家评审成为可能。

### 第 10 步：回放
建议讲：
> replay 的意义不是“录像回放”，而是把一次任务和决策过程按事件链重建出来。  
> 这使系统具备可解释性：不仅知道结果是什么，还知道为什么 allow、deny、require_confirm 或 preempt。

### 第 11 步：收尾
建议讲：
> 最后再次回到测试，是为了说明这个系统不是靠现场人工解释勉强跑通，而是已经被测试锁定了一部分行为边界。  
> 这使它能够作为后续 fake adapter 增强、PX4 SITL 接入和专家展示的稳定基线。

---

## 五、你可以用来概括整个项目的一段话

> 当前这个项目的核心不是直接发飞控命令，而是先建立一套控制面内核。  
> 它的主链路是：  
> `mission_request -> action_request -> policy_decision_event -> adapter -> action_result -> audit/replay`  
> 其中：
> - `canonical protocol_json` 负责控制面表达
> - `unified_policy_gate` 负责唯一裁决入口
> - `adapter gateway` 负责把控制面映射到执行面
> - `fake adapter` 负责当前阶段的最小执行闭环  
> 因此，后续接 PX4 SITL / MAVLink，理论上不需要推倒控制面协议，只需要在 adapter 层扩展。

---

## 六、如果现场有人问“现在到底做到了什么”
可以直接回答：

> 当前已经形成一个 UAV-Agent Runtime v0.1 基线。  
> 它具备：
> 1. 稳定的控制面协议骨架  
> 2. policy gate 策略裁决入口  
> 3. 最小 runtime 主链路  
> 4. adapter gateway 与 fake adapter  
> 5. audit / replay 能力  
> 6. 测试闭环  
>
> 当前还没有做的是：
> - 真实飞控接入
> - PX4 SITL / MAVLink 适配
> - GUI 控制台
> - 多机协同  
>
> 但当前架构的价值在于：这些东西后续可以在不破坏控制面 contract 的前提下逐步接入。

---

## 七、现场演示时长建议

### 5 分钟版本
按下面顺序：
1. 激活环境  
2. `python -m pytest -q`  
3. `--help`  
4. `show-status`  
5. `show-audit`  
6. `replay-last`

### 10 分钟版本
在上面基础上加：
- 解释主链路
- 解释控制面 / 执行面分离
- 解释后续接 PX4 SITL 的位置

---

## 八、注意事项
1. 如果 PowerShell 不允许执行脚本，先执行：
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

2. 如果 `uav_runtime` 模块找不到，先设置：
```powershell
$env:PYTHONPATH = "$PWD\src"
```

3. 如果 `conda-unpack` 不存在，说明当前环境可能不是通过 conda-pack 恢复的；这时可跳过，但建议确认 Python 路径是否正确。

4. 若全量 `pytest` 在目标机上通过，说明：
- 当前 baseline 已可迁移
- 当前 skeleton / contract / tests 已保持一致
- 后续可以开始推进 demo 与适配器增强

---

## 九、建议现场目录
建议把这个文件与项目放在一起，例如：

```text
D:\2026UAVSwarm\docs\现场演示脚本_目标机.md
```

这样目标机上随时可以打开照着执行。
