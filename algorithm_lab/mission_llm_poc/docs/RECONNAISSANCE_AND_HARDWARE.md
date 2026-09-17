# Repository and hardware inspection

检查日期：2026-09-16（续作于09-17）。依据本机代码和只读命令输出，未访问远程 PR 状态。

## 代码证据

| 范围 | 检查版本 | 与算法实验相关的变化 |
| --- | --- | --- |
| 主线 / 本实验基线 | b4e2f6e | 本地提交历史显示 PR #74 已合并；三机巡检、health、GCS heartbeat 改进 |
| Runtime 生命周期分支 | 3fa42eb | TAKEOFF/LAND 遥测完成证据、幂等性、校准位置及健康证据契约 |
| 前端控制分支 | a20d658 | 节点绑定的 Runtime action controls |
| Integration 工作区 | b4e2f6e | 审计时仍与主线一致 |

未把其他分支的实现合入算法工作区。其契约仅作为接入设计参考，不作为已合并依赖。
没有检查或推断真实 PX4/Gazebo 飞行验收是否已完成。

主线 agent 仍为 TemplateAgentPlanner；新版 Runtime 分支状态字段仍标记
llm_enabled=false、real_execution_enabled=false。模型推理尚未接入。
新版动作契约区分 ACK 与真实遥测完成，GOTO/HOLD/RETURN_HOME 仍 proposal-only。

Runtime 新版公共位置需满足 spatial.public_position_usable，读取 spatial.scene_pose；
必须检查 scene/map、样本和标定有效期。旧顶层 pose 不能用来推定公共坐标。
新 Runtime 仅接受显式 NED-aligned 平移；主线 standalone patrol helper 则含 spawn yaw
旋转。这是两套不同假设，不可互换。算法实验不导入 patrol 控制器或自行标定。

## 实测硬件和环境

| 项目 | 结果 |
| --- | --- |
| GPU | NVIDIA GeForce RTX 4050 Laptop GPU |
| 显存 | 6141 MiB，总量约6 GiB；首次快照可用5921 MiB |
| NVIDIA driver | 566.24 |
| nvidia-smi CUDA 字段 | 12.7，表示驱动支持能力，不证明 CUDA Toolkit 已安装 |
| CPU | 13th Gen Intel Core i7-13620H，16 个逻辑处理器 |
| RAM | 16,890,519,552 bytes，约15.73 GiB |
| 当时可用 RAM | 3,034,238,976 bytes，约2.83 GiB，随进程变化 |
| D盘可用 | 576,883,159,040 bytes，约537.26 GiB |
| C盘可用 | 65,241,612,288 bytes，约60.76 GiB |
| 原有 Python | Anaconda Python 3.11.7 |
| 原有 PyTorch | 2.2.2+cu121；CUDA available=true；不在实验 .venv 内 |
| WSL | WSL2 的 Ubuntu / Ubuntu-22.04 等已安装，检查时停止 |
| Docker | CLI29.3.1可用；引擎未运行 |
| Ollama / uv | 未在 PATH 找到，不等价于整机绝对未安装 |

普通权限 CIM/WSL 查询遇到访问限制；RAM/磁盘改用只读 psutil/shutil，
WSL/Docker在允许的提权只读检查中确认。未启动 WSL/Docker、未停止其他进程。

## 部署结论

27B BF16权重理论上约54GB，单此一项已远超本机6GB显存；实际运行还需缓存和工作区。
上一轮大模型优先建议不适合直接在本机落地。第一轮应评估较小模型的低比特量化，
采用有界输入与短输出，并实测空闲内存、加载峰值、延迟和质量。
CPU offload不是免费扩容：本机当时可用内存也很有限。

Step 3 将重新核实当时可获得的候选模型和 Windows 推理支持，提供精确模型ID、
revision、量化文件、大小/哈希、许可证、目录和下载命令。当前没有冻结具体型号、
下载任何权重或安装模型框架，也不沿用未重新核实的“最新最好”结论。

独立实验环境只安装 jsonschema 和其间接依赖。源码目录及模块名均不含 codex；
Git 分支保留 codex/algorithm-lab-local-llm-poc 标识，和项目文件名无关。
