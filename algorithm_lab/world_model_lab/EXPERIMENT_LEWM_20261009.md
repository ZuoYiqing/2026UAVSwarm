# LeWorldModel 视觉离线准备与加载尝试：2026-10-09

## 实际状态

工作区：`D:\2026UAVSwarm-worktrees\algorithm-lab-local-llm-poc`；分支
`codex/algorithm-lab-local-llm-poc`，本轮基线 `f26dcec`。改动仅在
`algorithm_lab/world_model_lab/`。没有修改 Runtime、Policy、PX4/Gazebo 或前端。
资产、环境、缓存、临时文件、报告均在 D 盘；本轮没有训练模型。

已完成：

- 下载官方 PushT `weights.pt`（72,290,721 字节）和配置，固定 revision，
  实测 SHA-256 与官方权重文件清单一致。完整版本与哈希见 `LEWM_OFFLINE.md`。
- 固定官方源码版本，保留 MIT 许可证；在忽略的 `artifacts/lewm/vendor/`。
- 新建独立 Python 3.11 环境，无 system-site-packages；只从 D 盘 wheelhouse
  安装 PyTorch 2.6.0+cpu、Transformers 4.40.2 等。`pip check` 通过。
  没有修改根依赖和全局 Python 环境。
- 写好严格加载、三帧 RGB 输入、条件预测、离线 API 阻断、时延/内存记录程序。
  目前这条 ML 加载/预测路径尚未实测通过，不得标记为已验证实现。
- 15 项标准库单元测试通过，其中 5 项为视觉契约、样例和保护逻辑测试。
  测试没有导入 PyTorch，不属于真实模型实验。

## 完整输入与实际结果

运行命令（模块目录）：

```text
artifacts/lewm/.venv/Scripts/python.exe scripts/lewm_offline_probe.py --assets artifacts/lewm --output artifacts/lewm/runs/cpu_smoke_01 --device cpu
```

输入保存为 `runs/cpu_smoke_01/inputs/request.json` 和 `frame0.png` 至
`frame2.png`：三张 224×224 的人工 RGB 图，三组 10 维零值的已归一化 PushT
动作。不是无人机视频，也不对应任何真实飞行命令。请求契约明确声明
`fixture_kind=synthetic_rgb_io_smoke`，不具有任务准确率标签。

实际 `report.json`：

```json
{
  "status": "blocked",
  "reason": "MEMORY_GUARD: 1.17 GiB available; require 3.0",
  "available_memory_before_bytes": 1255383040,
  "model_loaded": false,
  "inference_completed": false,
  "board_validated": false,
  "execution_authorized": false
}
```

这是资源拒绝，发生在导入 PyTorch **之前**。无特征输出、时延、GPU 内存或
功耗测量结果；离线 socket 阻断检查也尚未执行。不能宣称模型成功加载、
推理失败或正式断网运行通过。没有降低保护阈值或关闭用户程序。

## 离线迁移包

打包程序携带最小推理代码、固定权重/配置/官方源码/许可、完整三帧样例、
可选 Windows CPU wheelhouse 和依赖锁，以及上面的受阻报告。逐文件 SHA-256
校验。manifest 的 `model_inference_validated_on_source=false` 与
`target_board_verified=false` 保持真实状态。

离线安装及迁移步骤见 `LEWM_OFFLINE.md`。Windows/x64 wheels 不适用 Orin。
本次包准备不等于 ARM64 部署成功；板卡版本和实际访问方式尚未确认。

## 下次复跑与验收

1. 本机可用内存达到至少 3GiB，使用新的输出目录复跑；保留完整输入/输出。
2. 通过严格权重键匹配、有限值、固定形状、重复推理和 socket 阻断检查后，
   再标记 CPU 离线加载/推理通过。需区分代码测试、API 阻断与系统断网验证。
3. 记录实际 Orin 的 JetPack/Python/CUDA/PyTorch、功耗模式与冷却，准备 ARM64
   离线依赖，断网冷启动；测 p50/p95、内存、原始 tegrastats 功率轨。
4. 更晚才进入真实轨迹预测质量与无人机域迁移，不能由 PushT 冒烟推断。

本实验的大型权重、隔离环境和运行产物由 Git 忽略；源码与实验文档可独立提交。
